"""HTTP coverage for `POST /api/v1/tasks/{task_id}/mark-missed`.

Four cases:

  1. Happy path — status transitions open → missed, ``tasks.marked_missed``
     audit entry is written.
  2. Permission — caller without ``tasks.write`` grant → 403.
  3. Transition guard — POST on a ``done`` task → 409.
  4. Transition guard — POST twice → second call 409 (already missed).

Run with: ``uv run pytest tests/test_tasks_mark_missed.py``
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.audit.models import AuditLog
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
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
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
    title: str,
    assigned_to_id: uuid.UUID,
    status: TaskStatus = TaskStatus.open,
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
            )
            session.add(t)
            await session.commit()
            return t.id
    finally:
        reset_context(token)


async def _fetch_task_status(
    org_id: uuid.UUID, task_id: uuid.UUID
) -> TaskStatus:
    from tests.conftest import TestSession

    ctx = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            row = await session.execute(select(Task).where(Task.id == task_id))
            t = row.scalar_one()
            return t.status
    finally:
        reset_context(ctx)


async def _fetch_audit_actions(
    org_id: uuid.UUID, entity_id: uuid.UUID
) -> list[str]:
    from tests.conftest import TestSession

    ctx = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            rows = (
                await session.execute(
                    select(AuditLog.action).where(AuditLog.entity_id == entity_id)
                )
            ).all()
            return [r[0] for r in rows]
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_mark_missed_happy_path(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    task_id = await _seed_task(
        org.id, title="Follow up",
        assigned_to_id=user.legacy_uuid, status=TaskStatus.open,
    )

    res = await layered_client.post(
        f"/api/v1/tasks/{task_id}/mark-missed", headers=headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "missed"

    # DB state matches the response
    assert await _fetch_task_status(org.id, task_id) == TaskStatus.missed

    # Audit trail includes the marked_missed action
    audit_actions = await _fetch_audit_actions(org.id, task_id)
    assert "tasks.marked_missed" in audit_actions


@pytest.mark.asyncio
async def test_mark_missed_requires_tasks_write_permission(
    layered_client, seeded_admin
):
    """No ``tasks.write`` grant → 403 from the router-level guard."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Deliberately grant only tasks.read.
    await _grant(seeded_admin["role"].id, "tasks.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    task_id = await _seed_task(
        org.id, title="No perms",
        assigned_to_id=user.legacy_uuid, status=TaskStatus.open,
    )

    res = await layered_client.post(
        f"/api/v1/tasks/{task_id}/mark-missed", headers=headers
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_mark_missed_refuses_transition_from_done(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    task_id = await _seed_task(
        org.id, title="Already done",
        assigned_to_id=user.legacy_uuid, status=TaskStatus.done,
    )

    res = await layered_client.post(
        f"/api/v1/tasks/{task_id}/mark-missed", headers=headers
    )
    assert res.status_code == 409, res.text
    assert await _fetch_task_status(org.id, task_id) == TaskStatus.done


@pytest.mark.asyncio
async def test_mark_missed_second_call_is_409(layered_client, seeded_admin):
    """Idempotency guard — second POST returns 409 because the row is
    now terminal (``missed``)."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    task_id = await _seed_task(
        org.id, title="Twice",
        assigned_to_id=user.legacy_uuid, status=TaskStatus.open,
    )
    first = await layered_client.post(
        f"/api/v1/tasks/{task_id}/mark-missed", headers=headers
    )
    assert first.status_code == 200

    second = await layered_client.post(
        f"/api/v1/tasks/{task_id}/mark-missed", headers=headers
    )
    assert second.status_code == 409
