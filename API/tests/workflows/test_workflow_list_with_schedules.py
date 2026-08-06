"""DAL pin tests for ``tasks/workflow-scheduling`` Step 5.

Covers:
  * Unscheduled workflow row returns count=0, next=None.
  * Scheduled workflow row returns count=N, next=min(next_run_at).
  * Paused schedules do NOT count toward ``active_schedule_count``.
  * ``has_schedule=True`` narrows to workflows with ≥1 active schedule.
  * ``has_schedule=False`` narrows to the complement.
  * Single-SELECT query shape (no N+1 across N workflows).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy import text as sql_text

from src.app.core.workflows import data_access as workflows_da
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    OnMissedPolicy,
    ScheduleKind,
    Workflow,
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


async def _seed_workflow(test_db, *, org_id: uuid.UUID, name: str) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=name,
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


def _mk_schedule(
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    next_run_at: datetime,
    active: bool = True,
    name: str = "s",
) -> WorkflowSchedule:
    return WorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        name=name,
        schedule_kind=ScheduleKind.daily,
        config_json={"time": "09:00"},
        timezone="UTC",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        next_run_at=next_run_at,
        active=active,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=ConcurrencyPolicy.forbid,
        runs_completed=0,
    )


async def test_unscheduled_workflow_returns_zero_count_and_null_next(test_db, org_id):
    await _seed_workflow(test_db, org_id=org_id, name="lonely")

    rows, total = await workflows_da.list_workflows_with_schedule_summary(test_db, org_id=org_id)
    assert total == 1
    _wf, count, nxt = rows[0]
    assert count == 0
    assert nxt is None


async def test_scheduled_workflow_returns_count_and_min_next_run(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id, name="scheduled")
    now = datetime.now(UTC)
    for i, offset_h in enumerate((3, 1, 5)):
        sch = _mk_schedule(
            org_id=org_id,
            workflow_id=wf.id,
            next_run_at=now + timedelta(hours=offset_h),
            name=f"s{i}",
        )
        await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    rows, _ = await workflows_da.list_workflows_with_schedule_summary(test_db, org_id=org_id)
    _wf, count, nxt = rows[0]
    assert count == 3
    assert nxt is not None
    # Earliest of {now+3h, now+1h, now+5h} = now+1h.
    assert (now + timedelta(minutes=55)) < nxt < (now + timedelta(minutes=65))


async def test_paused_schedules_do_not_count(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id, name="mixed")
    now = datetime.now(UTC)
    active = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now + timedelta(hours=2),
        active=True,
        name="active",
    )
    paused = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now + timedelta(hours=1),
        active=False,
        name="paused",
    )
    await workflows_da.insert_schedule(test_db, schedule=active)
    await workflows_da.insert_schedule(test_db, schedule=paused)
    await test_db.commit()

    rows, _ = await workflows_da.list_workflows_with_schedule_summary(test_db, org_id=org_id)
    _wf, count, nxt = rows[0]
    assert count == 1, "paused schedule leaked into active count"
    # Should reflect the ACTIVE schedule's next_run_at, not the paused one.
    assert nxt is not None
    assert (
        (now + timedelta(hours=2) - timedelta(minutes=5))
        < nxt
        < (now + timedelta(hours=2) + timedelta(minutes=5))
    )


async def test_has_schedule_true_narrows_to_scheduled(test_db, org_id):
    wf_scheduled = await _seed_workflow(test_db, org_id=org_id, name="has-sched")
    wf_unscheduled = await _seed_workflow(test_db, org_id=org_id, name="no-sched")
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf_scheduled.id,
        next_run_at=now + timedelta(hours=1),
    )
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    rows, total = await workflows_da.list_workflows_with_schedule_summary(
        test_db, org_id=org_id, has_schedule=True
    )
    ids = {r[0].id for r in rows}
    assert wf_scheduled.id in ids
    assert wf_unscheduled.id not in ids
    assert total == 1


async def test_has_schedule_false_narrows_to_unscheduled(test_db, org_id):
    wf_scheduled = await _seed_workflow(test_db, org_id=org_id, name="has-sched")
    wf_unscheduled = await _seed_workflow(test_db, org_id=org_id, name="no-sched")
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf_scheduled.id,
        next_run_at=now + timedelta(hours=1),
    )
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    rows, total = await workflows_da.list_workflows_with_schedule_summary(
        test_db, org_id=org_id, has_schedule=False
    )
    ids = {r[0].id for r in rows}
    assert wf_unscheduled.id in ids
    assert wf_scheduled.id not in ids
    assert total == 1


async def test_list_with_summary_runs_bounded_select_count(test_db, org_id):
    """N+1 guard: listing N workflows must run a constant number of
    SELECTs (rows + total), not O(N). Seeds 10 workflows + 30 mixed
    schedules and asserts SELECT count ≤ 3."""
    now = datetime.now(UTC)
    for i in range(10):
        wf = await _seed_workflow(test_db, org_id=org_id, name=f"wf-{i}")
        for j in range(3):
            sch = _mk_schedule(
                org_id=org_id,
                workflow_id=wf.id,
                next_run_at=now + timedelta(hours=j + 1),
                name=f"s{i}-{j}",
            )
            await workflows_da.insert_schedule(test_db, schedule=sch)
        await test_db.commit()

    select_count = 0

    def _tap(conn, cursor, statement, parameters, context, executemany):
        nonlocal select_count
        if statement.strip().upper().startswith("SELECT"):
            select_count += 1

    engine = test_db.get_bind().sync_engine
    event.listen(engine, "before_cursor_execute", _tap)
    try:
        rows, total = await workflows_da.list_workflows_with_schedule_summary(
            test_db, org_id=org_id, limit=50
        )
    finally:
        event.remove(engine, "before_cursor_execute", _tap)

    assert total == 10
    assert len(rows) == 10
    # Two queries: total (COUNT) + the main SELECT with aggregate
    # subqueries. Anything higher is an N+1 regression.
    assert select_count <= 3, f"suspected N+1: {select_count} SELECTs for a 10-workflow list"
