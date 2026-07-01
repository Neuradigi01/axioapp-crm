"""Coverage for the nightly ``groom_stale_open_tasks`` Celery task.

Four cases:

  1. Stale-open (> 7 days past due) → flipped to ``missed``.
  2. Recently-open (5 days past due) → NOT flipped (within grace).
  3. Terminal-status (``done``) → NOT flipped (already closed).
  4. Cross-tenant sweep — eligible rows in two different orgs both
     get flipped in one run.

Calls the internal async coroutine directly so we run inside pytest's
event loop (the sync entry point wraps this in ``asyncio.run`` for
Celery worker prefork).

Run with: ``uv run pytest tests/test_tasks_groom_stale.py``
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text as sql_text

from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.tasks.tasks import _groom_stale_open_tasks_async
from src.app.core.tenants.models import Organization
from src.app.shared.context import RequestContext, reset_context, set_context


async def _seed_org(*, slug: str) -> Organization:
    from tests.conftest import TestSession

    async with TestSession() as session:
        org = Organization(id=uuid.uuid4(), name="Demo", slug=slug)
        session.add(org)
        await session.commit()
        return org


async def _seed_task_with_pinned_updated_at(
    org_id: uuid.UUID,
    *,
    title: str,
    due_at: datetime,
    status: TaskStatus,
) -> uuid.UUID:
    """Insert a Task with a specific ``due_at``. ``updated_at`` uses
    the server default so the ``UPDATE ... RETURNING`` query sees a
    fresh row shape."""
    from tests.conftest import TestSession

    tk = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            t = Task(
                org_id=org_id,
                title=title,
                assigned_to_id=uuid.uuid4(),
                due_at=due_at,
                status=status,
            )
            session.add(t)
            await session.commit()
            return t.id
    finally:
        reset_context(tk)


async def _fetch_status(org_id: uuid.UUID, task_id: uuid.UUID) -> TaskStatus:
    from tests.conftest import TestSession

    tk = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            row = await session.execute(select(Task).where(Task.id == task_id))
            return row.scalar_one().status
    finally:
        reset_context(tk)


@pytest.mark.asyncio
async def test_stale_open_task_is_flipped_to_missed(layered_client, seeded_admin):
    """The grooming query targets ``status='open' AND due_at < now - 7d``."""
    org_id = seeded_admin["org"].id
    now = datetime.now(UTC)
    task_id = await _seed_task_with_pinned_updated_at(
        org_id,
        title="stale open",
        due_at=now - timedelta(days=8),
        status=TaskStatus.open,
    )

    result = await _groom_stale_open_tasks_async()

    assert result["swept"] >= 1
    assert await _fetch_status(org_id, task_id) == TaskStatus.missed


@pytest.mark.asyncio
async def test_recent_overdue_task_is_not_touched(layered_client, seeded_admin):
    """5-day-old open task is still inside the grace window."""
    org_id = seeded_admin["org"].id
    now = datetime.now(UTC)
    task_id = await _seed_task_with_pinned_updated_at(
        org_id,
        title="recent overdue",
        due_at=now - timedelta(days=5),
        status=TaskStatus.open,
    )

    await _groom_stale_open_tasks_async()

    assert await _fetch_status(org_id, task_id) == TaskStatus.open


@pytest.mark.asyncio
async def test_terminal_status_is_not_touched(layered_client, seeded_admin):
    """Already-``done`` rows are terminal — grooming skips them even if
    ``due_at`` is 10 days old."""
    org_id = seeded_admin["org"].id
    now = datetime.now(UTC)
    task_id = await _seed_task_with_pinned_updated_at(
        org_id,
        title="old but done",
        due_at=now - timedelta(days=10),
        status=TaskStatus.done,
    )

    await _groom_stale_open_tasks_async()

    assert await _fetch_status(org_id, task_id) == TaskStatus.done


@pytest.mark.asyncio
async def test_cross_tenant_sweep_flips_rows_in_both_orgs(
    layered_client, seeded_admin
):
    """The grooming query uses raw SQL to deliberately bypass the
    per-tenant RLS filter — one run touches every org's eligible rows."""
    org_a = seeded_admin["org"]
    org_b = await _seed_org(slug=f"other-{uuid.uuid4().hex[:6]}")

    now = datetime.now(UTC)
    task_a = await _seed_task_with_pinned_updated_at(
        org_a.id,
        title="stale in org A",
        due_at=now - timedelta(days=8),
        status=TaskStatus.open,
    )
    task_b = await _seed_task_with_pinned_updated_at(
        org_b.id,
        title="stale in org B",
        due_at=now - timedelta(days=8),
        status=TaskStatus.open,
    )

    await _groom_stale_open_tasks_async()

    assert await _fetch_status(org_a.id, task_a) == TaskStatus.missed
    assert await _fetch_status(org_b.id, task_b) == TaskStatus.missed
