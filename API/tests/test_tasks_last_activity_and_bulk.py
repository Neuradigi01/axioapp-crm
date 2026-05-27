"""HTTP coverage for tasks `last_activity_at` + bulk endpoints (Step 1).

Six cases:

  1. Activity-insert on a task bumps `last_activity_at`.
  2. `update_task` (title change) bumps `last_activity_at` independent
     of any activity row.
  3. `POST /tasks/bulk-reassign` over three tasks updates every row
     and writes three `reassign` audit activities.
  4. `POST /tasks/bulk-mark-done` mixing open + already-done tasks
     returns `{done: N, skipped: M}` partial-success.
  5. `POST /tasks/bulk-delete` removes the targeted rows.
  6. `GET /tasks/all?sort_by=last_activity_at&sort_dir=desc` returns
     newest-activity-first (NULLs last).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tasks.models import Task, TaskStatus
from src.app.shared.context import RequestContext, reset_context, set_context


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_task(
    org_id: uuid.UUID,
    *,
    assigned_to_id: uuid.UUID,
    title: str = "Call customer",
    status: TaskStatus = TaskStatus.open,
    last_activity_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            t = Task(
                org_id=org_id,
                title=title,
                assigned_to_id=assigned_to_id,
                status=status,
                last_activity_at=last_activity_at,
            )
            session.add(t)
            await session.commit()
            return t.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_activity_insert_bumps_task_last_activity_at(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "tasks.read",
        "tasks.write",
        "activities.read",
        "activities.write",
    )
    task_id = await _seed_task(org.id, assigned_to_id=user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/activities",
        json={
            "entity_type": "task",
            "entity_id": str(task_id),
            "type": "note",
            "payload": {"text": "left a voicemail"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Task).where(Task.id == task_id))
            ).scalar_one()
            assert row.last_activity_at is not None
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_update_task_bumps_last_activity_at(
    layered_client, seeded_admin
):
    """A title edit doesn't create an activity row, but the user
    still expects `last_activity_at` to reflect the edit."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    task_id = await _seed_task(org.id, assigned_to_id=user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"title": "Call customer back"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Task).where(Task.id == task_id))
            ).scalar_one()
            assert row.last_activity_at is not None
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_reassign_writes_activity_per_row(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")

    # Seed under a different placeholder owner so the reassign
    # actually moves them. We can't easily create a second user in
    # this fixture; use the same user but seed with the same
    # legacy_uuid and verify the activity rows write regardless —
    # actually no: bulk_reassign skips rows already owned by the
    # target. So we must seed with a different uuid then reassign
    # to user.legacy_uuid.
    other_uuid = uuid.uuid4()
    # The DB FK is `users(id)` (the UUID shim) — insert that row
    # so we can use it as a temporary owner.
    async with TestSession() as session:
        from sqlalchemy import text as sql_text
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": str(other_uuid)},
        )
        await session.commit()

    ids = [
        await _seed_task(
            org.id,
            assigned_to_id=other_uuid,
            title=f"Task {i}",
        )
        for i in range(3)
    ]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/tasks/bulk-reassign",
        json={
            "ids": [str(i) for i in ids],
            "assigned_to_id": str(user.legacy_uuid),
            "note": "shift handover",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reassigned"] == 3

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            for tid in ids:
                row = (
                    await session.execute(select(Task).where(Task.id == tid))
                ).scalar_one()
                assert row.assigned_to_id == user.legacy_uuid

            activities = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "task")
                    .where(Activity.entity_id.in_(ids))
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(activities) == 3
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_mark_done_partial_success_with_already_done(
    layered_client, seeded_admin
):
    """Mixing open + already-done tasks → `{done, skipped}` split."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")

    open_a = await _seed_task(org.id, assigned_to_id=user.legacy_uuid, title="Open A")
    open_b = await _seed_task(org.id, assigned_to_id=user.legacy_uuid, title="Open B")
    already = await _seed_task(
        org.id,
        assigned_to_id=user.legacy_uuid,
        title="Already done",
        status=TaskStatus.done,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/tasks/bulk-mark-done",
        json={"ids": [str(open_a), str(open_b), str(already)]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == 2
    assert body["skipped"] == 1


@pytest.mark.asyncio
async def test_bulk_delete_removes_rows(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    ids = [
        await _seed_task(
            org.id, assigned_to_id=user.legacy_uuid, title=f"Drop {i}"
        )
        for i in range(2)
    ]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/tasks/bulk-delete",
        json={"ids": [str(i) for i in ids]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 2

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            remaining = (
                await session.execute(select(Task).where(Task.id.in_(ids)))
            ).scalars().all()
            assert remaining == []
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_list_sort_by_last_activity_desc_nulls_last(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id, "tasks.read", "tasks.write", "users.read"
    )

    now = datetime.now(timezone.utc)
    older = await _seed_task(
        org.id,
        assigned_to_id=user.legacy_uuid,
        title="Older activity",
        last_activity_at=now - timedelta(hours=3),
    )
    newer = await _seed_task(
        org.id,
        assigned_to_id=user.legacy_uuid,
        title="Newer activity",
        last_activity_at=now - timedelta(minutes=10),
    )
    never = await _seed_task(
        org.id, assigned_to_id=user.legacy_uuid, title="Never touched"
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        "/api/v1/tasks/all?sort_by=last_activity_at&sort_dir=desc",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids == [str(newer), str(older), str(never)]
