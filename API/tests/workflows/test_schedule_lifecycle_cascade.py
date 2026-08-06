"""Pin tests for ``tasks/workflow-scheduling`` Step 6 lifecycle
loops: contact-merge repoint, contact-delete deactivation, orphan-
run reaper, consecutive-empty auto-deactivation, weekly orphan-
schedule sweeper.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import data_access as workflows_da
from src.app.core.workflows import service as workflows_service
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    DeactivationReason,
    OnMissedPolicy,
    ScheduleKind,
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowSchedule,
    WorkflowStatus,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    oid = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(oid), "name": "Demo", "slug": f"demo-{oid.hex[:6]}"},
    )
    await test_db.commit()
    return oid


async def _seed_workflow(test_db, *, org_id: uuid.UUID) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph={
            "nodes": [{"id": "t1", "type": "trigger.lead_created"}],
            "edges": [],
        },
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _seed_contact(test_db, *, org_id: uuid.UUID) -> uuid.UUID:
    cid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, tags, custom_data) "
            "VALUES (:id, :org, :name, '{}'::text[], '{}'::jsonb)"
        ),
        {"id": str(cid), "org": str(org_id), "name": f"C-{cid.hex[:6]}"},
    )
    await test_db.commit()
    return cid


def _mk_schedule(
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
    active: bool = True,
    consecutive_empty_fires: int = 0,
    name: str = "s",
) -> WorkflowSchedule:
    return WorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        contact_id=contact_id,
        name=name,
        schedule_kind=ScheduleKind.daily,
        config_json={"time": "09:00"},
        timezone="UTC",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
        active=active,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=ConcurrencyPolicy.forbid,
        runs_completed=0,
        consecutive_empty_fires=consecutive_empty_fires,
    )


# ---------------------------------------------------------------------------
# Contact-delete cascade
# ---------------------------------------------------------------------------


async def test_cascade_deactivates_schedules_pointing_at_deleted_contact(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    contact_id = await _seed_contact(test_db, org_id=org_id)
    sch = _mk_schedule(org_id=org_id, workflow_id=wf.id, contact_id=contact_id, name="alive")
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    count = await workflows_service.cascade_schedules_on_contact_delete(
        test_db, org_id=org_id, contact_id=contact_id
    )
    assert count == 1

    refreshed = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    assert refreshed is not None
    assert refreshed.active is False
    assert refreshed.deactivation_reason == DeactivationReason.contact_deleted
    assert refreshed.next_run_at is None


async def test_cascade_is_noop_when_contact_has_no_schedules(test_db, org_id):
    contact_id = await _seed_contact(test_db, org_id=org_id)
    count = await workflows_service.cascade_schedules_on_contact_delete(
        test_db, org_id=org_id, contact_id=contact_id
    )
    assert count == 0


# ---------------------------------------------------------------------------
# Consecutive-empty auto-deactivation
# ---------------------------------------------------------------------------


async def test_bump_returns_incremented_value(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _mk_schedule(org_id=org_id, workflow_id=wf.id, consecutive_empty_fires=5)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    new_count = await workflows_da.bump_consecutive_empty_fires(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    await test_db.commit()
    assert new_count == 6


async def test_reset_zeroes_counter(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _mk_schedule(org_id=org_id, workflow_id=wf.id, consecutive_empty_fires=12)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    await workflows_da.reset_consecutive_empty_fires(test_db, org_id=org_id, schedule_id=sch.id)
    await test_db.commit()

    refreshed = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    assert refreshed is not None
    assert refreshed.consecutive_empty_fires == 0


async def test_deactivate_for_empty_fires_sets_reason(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _mk_schedule(org_id=org_id, workflow_id=wf.id, consecutive_empty_fires=20)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    await workflows_service.deactivate_schedule_for_empty_fires(
        test_db, org_id=org_id, schedule_id=sch.id
    )

    refreshed = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    assert refreshed is not None
    assert refreshed.active is False
    assert refreshed.deactivation_reason == DeactivationReason.consecutive_empty


# ---------------------------------------------------------------------------
# Orphan-run reaper
# ---------------------------------------------------------------------------


async def test_reap_orphaned_marks_old_pending_runs_errored(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    old_pending = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        started_at=datetime.now(UTC) - timedelta(hours=3),
    )
    fresh_pending = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    test_db.add_all([old_pending, fresh_pending])
    await test_db.commit()
    await test_db.refresh(old_pending)
    await test_db.refresh(fresh_pending)

    # Patch shared.db.async_session to use the test DB session so
    # ``reap_orphaned_pending_runs`` sees the fixtures we just seeded.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import src.app.shared.db as shared_db

    bind = test_db.get_bind()
    fake_sm = async_sessionmaker(bind, expire_on_commit=False)
    original = shared_db.async_session
    shared_db.async_session = fake_sm  # type: ignore[assignment]
    try:
        stats = await workflows_service.reap_orphaned_pending_runs(older_than_minutes=60, limit=100)
    finally:
        shared_db.async_session = original  # type: ignore[assignment]

    assert stats["reaped"] >= 1
    # Re-fetch fresh — expire_on_commit=False keeps the ORM instance stale.
    old_refreshed = (
        await test_db.execute(
            sql_text("SELECT status, error FROM tbl_workflow_runs WHERE id = :id"),
            {"id": str(old_pending.id)},
        )
    ).first()
    assert old_refreshed is not None
    assert old_refreshed[0] == "errored"
    assert old_refreshed[1] == "orphaned_pending"

    # Fresh pending untouched.
    fresh_row = (
        await test_db.execute(
            sql_text("SELECT status FROM tbl_workflow_runs WHERE id = :id"),
            {"id": str(fresh_pending.id)},
        )
    ).first()
    assert fresh_row is not None
    assert fresh_row[0] == "pending"


# ---------------------------------------------------------------------------
# Orphan-schedule weekly sweeper
# ---------------------------------------------------------------------------


async def test_list_orphan_schedules_returns_workflowless_rows(test_db, org_id):
    """Simulate the historical-bug case: schedule row exists but the
    parent workflow was dropped by a raw SQL delete that bypassed
    FK CASCADE. The sweeper must find it."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _mk_schedule(org_id=org_id, workflow_id=wf.id, name="soon-orphan")
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    # Simulate the FK-bypass: raw DELETE with the FK constraint
    # temporarily disabled. Postgres session_replication_role='replica'
    # disables user triggers + FK constraints for the current session.
    await test_db.execute(sql_text("SET session_replication_role = 'replica'"))
    try:
        await test_db.execute(
            sql_text("DELETE FROM tbl_workflows WHERE id = :id"),
            {"id": str(wf.id)},
        )
        await test_db.commit()
    finally:
        await test_db.execute(sql_text("SET session_replication_role = 'origin'"))

    orphans = await workflows_da.list_orphan_schedules(test_db, limit=100)
    orphan_ids = {o.id for o in orphans}
    assert sch.id in orphan_ids
