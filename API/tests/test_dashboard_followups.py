"""HTTP coverage for `GET /api/v1/dashboard/followups`.

Exercises the layered endpoint end-to-end for every bucket + filter
combination the widget uses. Each test seeds a minimal set of Tasks +
optionally Contacts via the ORM (bypasses the tasks POST path so we
can pin ``updated_at`` and ``due_at`` deterministically).

Run with: ``uv run pytest tests/test_dashboard_followups.py``
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tasks.models import (
    Task,
    TaskFollowupType,
    TaskPriority,
    TaskStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context


# --- Helpers ----------------------------------------------------------------


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


async def _seed_contact(
    org_id: uuid.UUID,
    *,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(org_id=org_id, full_name=full_name, phone=phone, email=email)
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_task(
    org_id: uuid.UUID,
    *,
    title: str,
    assigned_to_id: uuid.UUID,
    due_at: datetime | None,
    status: TaskStatus = TaskStatus.open,
    priority: TaskPriority = TaskPriority.med,
    followup_type: TaskFollowupType | None = None,
    updated_at: datetime | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    description: str | None = None,
) -> uuid.UUID:
    """Seed a Task via the ORM with explicit control over ``updated_at``.

    Direct DB write is intentional — the tasks POST endpoint stamps
    ``updated_at`` server-side, which we can't override, so the
    "completed today" and "missed last 7d" buckets need us to pin the
    timestamp here.
    """
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            t = Task(
                org_id=org_id,
                title=title,
                description=description,
                assigned_to_id=assigned_to_id,
                due_at=due_at,
                status=status,
                priority=priority,
                followup_type=followup_type,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
            )
            session.add(t)
            await session.flush()
            if updated_at is not None:
                # ``updated_at`` has an ``onupdate=now()`` on the ORM
                # column, so the session flush above stamped it. Pin
                # via raw UPDATE bypassing the onupdate hook.
                from sqlalchemy import text as sql_text

                await session.execute(
                    sql_text(
                        "UPDATE tbl_tasks SET updated_at = :u WHERE id = :id"
                    ),
                    {"u": updated_at, "id": t.id},
                )
            await session.commit()
            return t.id
    finally:
        reset_context(token)


def _today_noon() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, 12, 0, tzinfo=UTC)


# --- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_scope_returns_all_tasks_in_org(layered_client, seeded_admin):
    """Owner-like caller with ``users.read`` sees every assignee's tasks."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    other_uuid = uuid.uuid4()
    await _seed_task(
        org.id,
        title="Mine due today",
        assigned_to_id=user.legacy_uuid,
        due_at=_today_noon(),
        followup_type=TaskFollowupType.call,
    )
    await _seed_task(
        org.id,
        title="Someone else's due today",
        assigned_to_id=other_uuid,
        due_at=_today_noon() + timedelta(hours=1),
        followup_type=TaskFollowupType.email,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today", headers=headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "org"
    assert body["total"] == 2
    assignees = {row["assigned_to"]["id"] for row in body["items"]}
    assert {str(user.legacy_uuid), str(other_uuid)} == assignees


@pytest.mark.asyncio
async def test_personal_scope_filters_to_self_and_ignores_assigned_to_param(
    layered_client, seeded_admin
):
    """Employee scope pins ``assignee=self`` — the ``assigned_to`` query
    param is silently ignored so URL-hacking can't peek at peers."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # NB: no `users.read` grant → personal scope.
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    other_uuid = uuid.uuid4()
    await _seed_task(
        org.id,
        title="Mine",
        assigned_to_id=user.legacy_uuid,
        due_at=_today_noon(),
    )
    await _seed_task(
        org.id,
        title="Peer's task",
        assigned_to_id=other_uuid,
        due_at=_today_noon(),
    )

    # Base personal-scope call
    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today", headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["scope"] == "personal"
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Mine"

    # URL-hacking attempt: pass peer's uuid — still filters to self.
    res2 = await layered_client.get(
        f"/api/v1/dashboard/followups?bucket=today&assigned_to={other_uuid}",
        headers=headers,
    )
    body2 = res2.json()
    assert body2["total"] == 1
    assert body2["items"][0]["title"] == "Mine"


@pytest.mark.asyncio
async def test_bucket_today_sort_due_asc_then_priority_desc(
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

    noon = _today_noon()
    # Same due time, different priorities → priority ordering wins.
    await _seed_task(
        org.id, title="low prio noon",
        assigned_to_id=user.legacy_uuid, due_at=noon, priority=TaskPriority.low,
    )
    await _seed_task(
        org.id, title="high prio noon",
        assigned_to_id=user.legacy_uuid, due_at=noon, priority=TaskPriority.high,
    )
    await _seed_task(
        org.id, title="med prio noon",
        assigned_to_id=user.legacy_uuid, due_at=noon, priority=TaskPriority.med,
    )
    # Earlier due time — should sort ABOVE the noon rows regardless of priority.
    await _seed_task(
        org.id, title="low prio 9am",
        assigned_to_id=user.legacy_uuid,
        due_at=noon.replace(hour=9), priority=TaskPriority.low,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today", headers=headers
    )
    titles = [row["title"] for row in res.json()["items"]]
    assert titles == [
        "low prio 9am",
        "high prio noon",
        "med prio noon",
        "low prio noon",
    ]


@pytest.mark.asyncio
async def test_bucket_pending_excludes_terminal_statuses(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    noon = _today_noon()
    await _seed_task(
        org.id, title="open today",
        assigned_to_id=user.legacy_uuid, due_at=noon, status=TaskStatus.open,
    )
    await _seed_task(
        org.id, title="done today",
        assigned_to_id=user.legacy_uuid, due_at=noon, status=TaskStatus.done,
    )
    await _seed_task(
        org.id, title="cancelled today",
        assigned_to_id=user.legacy_uuid, due_at=noon, status=TaskStatus.cancelled,
    )
    await _seed_task(
        org.id, title="missed today",
        assigned_to_id=user.legacy_uuid, due_at=noon, status=TaskStatus.missed,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=pending", headers=headers
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "open today"


@pytest.mark.asyncio
async def test_bucket_completed_today_uses_updated_at(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    await _seed_task(
        org.id, title="done today",
        assigned_to_id=user.legacy_uuid, due_at=_today_noon(),
        status=TaskStatus.done, updated_at=now,
    )
    await _seed_task(
        org.id, title="done yesterday",
        assigned_to_id=user.legacy_uuid, due_at=_today_noon() - timedelta(days=1),
        status=TaskStatus.done, updated_at=yesterday,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=completed_today", headers=headers
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "done today"


@pytest.mark.asyncio
async def test_bucket_overdue_excludes_missed_and_cancelled(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    yesterday = _today_noon() - timedelta(days=1)
    tomorrow = _today_noon() + timedelta(days=1)
    await _seed_task(
        org.id, title="overdue open",
        assigned_to_id=user.legacy_uuid, due_at=yesterday, status=TaskStatus.open,
    )
    await _seed_task(
        org.id, title="future open",
        assigned_to_id=user.legacy_uuid, due_at=tomorrow, status=TaskStatus.open,
    )
    await _seed_task(
        org.id, title="already done overdue",
        assigned_to_id=user.legacy_uuid, due_at=yesterday, status=TaskStatus.done,
    )
    await _seed_task(
        org.id, title="already missed overdue",
        assigned_to_id=user.legacy_uuid, due_at=yesterday, status=TaskStatus.missed,
    )
    await _seed_task(
        org.id, title="already cancelled overdue",
        assigned_to_id=user.legacy_uuid, due_at=yesterday, status=TaskStatus.cancelled,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=overdue", headers=headers
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "overdue open"


@pytest.mark.asyncio
async def test_bucket_missed_last_7d_and_counts_match(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(UTC)
    yesterday_close = now - timedelta(days=1)
    eight_days_ago = now - timedelta(days=8)
    await _seed_task(
        org.id, title="missed yesterday",
        assigned_to_id=user.legacy_uuid,
        due_at=_today_noon() - timedelta(days=3),
        status=TaskStatus.missed, updated_at=yesterday_close,
    )
    await _seed_task(
        org.id, title="missed 8 days ago",
        assigned_to_id=user.legacy_uuid,
        due_at=_today_noon() - timedelta(days=15),
        status=TaskStatus.missed, updated_at=eight_days_ago,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=missed", headers=headers
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "missed yesterday"
    # The counts.missed_last_7d MUST match the missed-bucket total for
    # the same filter set.
    assert body["counts"]["missed_last_7d"] == 1


@pytest.mark.asyncio
async def test_search_matches_title_and_contact_fields(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_a = await _seed_contact(
        org.id, full_name="Rahul Sharma", phone="+919999888877",
    )
    await _seed_task(
        org.id, title="Send quote PDF",
        assigned_to_id=user.legacy_uuid, due_at=_today_noon(),
        related_entity_type="contact", related_entity_id=contact_a,
    )
    await _seed_task(
        org.id, title="Prep pipeline review",
        assigned_to_id=user.legacy_uuid, due_at=_today_noon(),
    )

    # Match on title
    res1 = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&q=quote", headers=headers
    )
    titles = {row["title"] for row in res1.json()["items"]}
    assert titles == {"Send quote PDF"}

    # Match on linked contact name
    res2 = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&q=rahul", headers=headers
    )
    titles = {row["title"] for row in res2.json()["items"]}
    assert titles == {"Send quote PDF"}

    # Match on contact phone
    res3 = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&q=99998888", headers=headers
    )
    titles = {row["title"] for row in res3.json()["items"]}
    assert titles == {"Send quote PDF"}


@pytest.mark.asyncio
async def test_followup_type_filter(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    noon = _today_noon()
    await _seed_task(
        org.id, title="call one",
        assigned_to_id=user.legacy_uuid, due_at=noon,
        followup_type=TaskFollowupType.call,
    )
    await _seed_task(
        org.id, title="email one",
        assigned_to_id=user.legacy_uuid, due_at=noon,
        followup_type=TaskFollowupType.email,
    )
    await _seed_task(
        org.id, title="no type",
        assigned_to_id=user.legacy_uuid, due_at=noon, followup_type=None,
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&followup_type=email",
        headers=headers,
    )
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "email one"


@pytest.mark.asyncio
async def test_pagination(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    noon = _today_noon()
    for i in range(7):
        await _seed_task(
            org.id, title=f"row {i}",
            assigned_to_id=user.legacy_uuid,
            due_at=noon + timedelta(minutes=i),
        )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&page=1&page_size=5",
        headers=headers,
    )
    body = res.json()
    assert body["total"] == 7
    assert len(body["items"]) == 5
    assert body["page"] == 1
    assert body["page_size"] == 5

    res2 = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today&page=2&page_size=5",
        headers=headers,
    )
    body2 = res2.json()
    assert body2["total"] == 7
    assert len(body2["items"]) == 2


@pytest.mark.asyncio
async def test_counts_include_empty_missed_when_no_missed_tasks(
    layered_client, seeded_admin
):
    """``missed_last_7d`` is always populated (default 0) so the widget's
    KPI chip counter never crashes on a fresh org."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client, org_slug=org.slug,
        email=user.email, password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await _seed_task(
        org.id, title="just one open task",
        assigned_to_id=user.legacy_uuid, due_at=_today_noon(),
    )

    res = await layered_client.get(
        "/api/v1/dashboard/followups?bucket=today", headers=headers
    )
    body = res.json()
    assert body["counts"]["missed_last_7d"] == 0
    assert body["counts"]["today_total"] == 1
