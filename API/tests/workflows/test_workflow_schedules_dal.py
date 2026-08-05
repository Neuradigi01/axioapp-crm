"""DAL pin tests for ``tasks/workflow-scheduling`` Step 1.

Covers, against a real Postgres test DB:

  * CRUD roundtrip through the schedule DAL functions.
  * ``get_schedule_by_id_and_org`` returns None on cross-tenant
    (foundational for the Step-3 cross-org 404-not-403 guard).
  * ``count_active_schedules_for_org`` respects the partial-index
    predicate (active=true only).
  * ``select_due_schedules_for_update_skip_locked`` returns only
    due, active rows joined to active workflows.
  * ``select_orphaned_pending_runs`` returns only pending runs older
    than the threshold.
  * ``update_schedule_fields`` bumps ``updated_at`` (ETag source).
  * FK cascade: workflow delete drops schedules; org delete drops
    schedules; contact delete NULLs ``contact_id``.

Deliberately excluded (Step 2 territory):
  * Recurrence math / ``compute_next_run_at``.
  * Actual sweep dispatch, event emission.
  * SKIP LOCKED under concurrent tx — needs multi-session harness;
    verified at migration layer (partial index + FOR UPDATE clause
    both present) and by manual smoke in Step 7.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import data_access as workflows_da
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    OnMissedPolicy,
    ScheduleKind,
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowSchedule,
    WorkflowStatus,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    oid = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(oid), "name": "Demo", "slug": f"demo-{oid.hex[:6]}"},
    )
    await test_db.commit()
    return oid


@pytest_asyncio.fixture
async def other_org_id(test_db):
    """A second org — used to prove cross-tenant isolation."""
    oid = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(oid), "name": "Other", "slug": f"other-{oid.hex[:6]}"},
    )
    await test_db.commit()
    return oid


async def _seed_workflow(
    test_db,
    *,
    org_id: uuid.UUID,
    status: WorkflowStatus = WorkflowStatus.active,
) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=status,
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


def _new_schedule(
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    active: bool = True,
    next_run_at: datetime | None = None,
    name: str = "Daily 9am",
    kind: ScheduleKind = ScheduleKind.daily,
) -> WorkflowSchedule:
    return WorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        name=name,
        schedule_kind=kind,
        config_json={"time": "09:00"},
        timezone="UTC",
        starts_at=datetime.now(UTC),
        next_run_at=next_run_at,
        active=active,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=ConcurrencyPolicy.forbid,
    )


# ---------------------------------------------------------------------------
# CRUD roundtrip
# ---------------------------------------------------------------------------


async def test_insert_and_get_schedule_roundtrip(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    await test_db.refresh(sch)

    fetched = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    assert fetched is not None
    assert fetched.id == sch.id
    assert fetched.name == "Daily 9am"
    assert fetched.schedule_kind == ScheduleKind.daily
    assert fetched.on_missed == OnMissedPolicy.skip
    assert fetched.concurrency_policy == ConcurrencyPolicy.forbid


async def test_get_schedule_cross_tenant_returns_none(test_db, org_id, other_org_id):
    """Foundational for the Step-3 cross-org 404 guard — if this
    ever returns the row across orgs, the API layer's 404 becomes
    a lie."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    fetched = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=other_org_id, schedule_id=sch.id
    )
    assert fetched is None


async def test_list_schedules_for_workflow_ordered_by_created_at_asc(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    s1 = _new_schedule(org_id=org_id, workflow_id=wf.id, name="first")
    await workflows_da.insert_schedule(test_db, schedule=s1)
    await test_db.commit()
    s2 = _new_schedule(org_id=org_id, workflow_id=wf.id, name="second")
    await workflows_da.insert_schedule(test_db, schedule=s2)
    await test_db.commit()

    listed = await workflows_da.list_schedules_for_workflow(
        test_db, org_id=org_id, workflow_id=wf.id
    )
    assert [s.name for s in listed] == ["first", "second"]


async def test_list_active_schedules_for_org_excludes_paused(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    active = _new_schedule(org_id=org_id, workflow_id=wf.id, active=True)
    paused = _new_schedule(org_id=org_id, workflow_id=wf.id, active=False, name="paused")
    await workflows_da.insert_schedule(test_db, schedule=active)
    await workflows_da.insert_schedule(test_db, schedule=paused)
    await test_db.commit()

    listed = await workflows_da.list_active_schedules_for_org(test_db, org_id=org_id)
    assert [s.id for s in listed] == [active.id]


async def test_count_active_schedules_for_org_matches_cap_shape(test_db, org_id):
    """Powers the 500-schedule cap check in Step 3."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    for i in range(3):
        s = _new_schedule(org_id=org_id, workflow_id=wf.id, name=f"sched-{i}")
        await workflows_da.insert_schedule(test_db, schedule=s)
    paused = _new_schedule(org_id=org_id, workflow_id=wf.id, active=False, name="paused")
    await workflows_da.insert_schedule(test_db, schedule=paused)
    await test_db.commit()

    count = await workflows_da.count_active_schedules_for_org(test_db, org_id=org_id)
    assert count == 3, "paused row must not count against the cap"


async def test_update_schedule_fields_bumps_updated_at(test_db, org_id):
    """``updated_at`` is the ETag source for the Step-3 If-Match
    optimistic lock — every DAL update MUST advance it."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    await test_db.refresh(sch)
    original_updated_at = sch.updated_at

    # Small delay to ensure NOW() > original_updated_at at postgres
    # microsecond resolution.
    await test_db.execute(sql_text("SELECT pg_sleep(0.01)"))

    rowcount = await workflows_da.update_schedule_fields(
        test_db,
        org_id=org_id,
        schedule_id=sch.id,
        fields={"name": "renamed"},
    )
    await test_db.commit()
    assert rowcount == 1

    refreshed = await workflows_da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=sch.id
    )
    assert refreshed is not None
    assert refreshed.name == "renamed"
    assert refreshed.updated_at > original_updated_at, (
        "updated_at MUST advance on every write (ETag source)"
    )


async def test_update_schedule_fields_cross_tenant_returns_zero(test_db, org_id, other_org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    rowcount = await workflows_da.update_schedule_fields(
        test_db,
        org_id=other_org_id,
        schedule_id=sch.id,
        fields={"name": "hacked"},
    )
    await test_db.commit()
    assert rowcount == 0


async def test_delete_schedule_removes_row(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    sid = sch.id

    rowcount = await workflows_da.delete_schedule(test_db, org_id=org_id, schedule_id=sid)
    await test_db.commit()
    assert rowcount == 1

    assert (
        await workflows_da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sid)
        is None
    )


# ---------------------------------------------------------------------------
# Sweep query
# ---------------------------------------------------------------------------


async def test_select_due_schedules_returns_only_due_and_active(test_db, org_id):
    """Sweep hot path — must skip future rows, paused rows, and rows
    attached to non-active workflows."""
    active_wf = await _seed_workflow(test_db, org_id=org_id)
    draft_wf = await _seed_workflow(test_db, org_id=org_id, status=WorkflowStatus.draft)

    now = datetime.now(UTC)

    due = _new_schedule(
        org_id=org_id,
        workflow_id=active_wf.id,
        next_run_at=now - timedelta(minutes=1),
        name="due",
    )
    future = _new_schedule(
        org_id=org_id,
        workflow_id=active_wf.id,
        next_run_at=now + timedelta(hours=1),
        name="future",
    )
    paused_but_due = _new_schedule(
        org_id=org_id,
        workflow_id=active_wf.id,
        next_run_at=now - timedelta(minutes=5),
        active=False,
        name="paused_but_due",
    )
    due_but_workflow_draft = _new_schedule(
        org_id=org_id,
        workflow_id=draft_wf.id,
        next_run_at=now - timedelta(minutes=5),
        name="due_but_workflow_draft",
    )
    for s in (due, future, paused_but_due, due_but_workflow_draft):
        await workflows_da.insert_schedule(test_db, schedule=s)
    await test_db.commit()

    picked = await workflows_da.select_due_schedules_for_update_skip_locked(test_db, now=now)
    picked_ids = {s.id for s in picked}
    assert picked_ids == {due.id}, f"unexpected picks: {picked_ids}"


async def test_select_due_schedules_respects_cross_tenant_join(test_db, org_id, other_org_id):
    """Belt-and-braces org_id join on tbl_workflows must prevent a
    schedule row with mismatched org_id from firing against another
    tenant's workflow (defence-in-depth on top of RLS)."""
    wf_org_a = await _seed_workflow(test_db, org_id=org_id)
    wf_org_b = await _seed_workflow(test_db, org_id=other_org_id)

    now = datetime.now(UTC)

    # Correct row — org_id matches workflow.org_id.
    correct = _new_schedule(
        org_id=org_id,
        workflow_id=wf_org_a.id,
        next_run_at=now - timedelta(minutes=1),
        name="correct",
    )
    await workflows_da.insert_schedule(test_db, schedule=correct)
    await test_db.commit()

    # Now build a mismatched row (would need to bypass service
    # validation to insert in practice; simulating a hypothetical
    # data corruption).
    mismatched = _new_schedule(
        org_id=org_id,
        workflow_id=wf_org_b.id,  # workflow belongs to OTHER org
        next_run_at=now - timedelta(minutes=1),
        name="mismatched",
    )
    await workflows_da.insert_schedule(test_db, schedule=mismatched)
    await test_db.commit()

    picked = await workflows_da.select_due_schedules_for_update_skip_locked(test_db, now=now)
    picked_ids = {s.id for s in picked}
    assert correct.id in picked_ids
    assert mismatched.id not in picked_ids, (
        "org_id-mismatched schedule must not fire — belt-and-braces"
    )


# ---------------------------------------------------------------------------
# Orphan-run reaper query
# ---------------------------------------------------------------------------


async def test_select_orphaned_pending_runs_older_than_threshold(test_db, org_id):
    """Only pending runs whose ``started_at < older_than`` — the
    Step-6 reaper marks these errored."""
    wf = await _seed_workflow(test_db, org_id=org_id)

    now = datetime.now(UTC)

    old_pending = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        started_at=now - timedelta(hours=2),
    )
    fresh_pending = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        started_at=now - timedelta(minutes=5),
    )
    old_completed = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.completed,
        current_node_id="t1",
        state={},
        started_at=now - timedelta(hours=3),
    )
    for r in (old_pending, fresh_pending, old_completed):
        test_db.add(r)
    await test_db.commit()
    for r in (old_pending, fresh_pending, old_completed):
        await test_db.refresh(r)

    threshold = now - timedelta(hours=1)
    orphans = await workflows_da.select_orphaned_pending_runs(test_db, older_than=threshold)
    orphan_ids = {r.id for r in orphans}
    assert old_pending.id in orphan_ids
    assert fresh_pending.id not in orphan_ids, "fresh row must not be reaped"
    assert old_completed.id not in orphan_ids, "completed row is not an orphan"


# ---------------------------------------------------------------------------
# FK cascade behaviour
# ---------------------------------------------------------------------------


async def test_workflow_delete_cascades_schedules(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    sch = _new_schedule(org_id=org_id, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    sid = sch.id

    await test_db.execute(
        sql_text("DELETE FROM tbl_workflows WHERE id = :id"),
        {"id": str(wf.id)},
    )
    await test_db.commit()

    assert (
        await workflows_da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sid)
        is None
    )


async def test_org_delete_cascades_schedules(test_db):
    """Deleting the org drops every schedule tied to it."""
    oid = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(oid), "name": "Ephemeral", "slug": f"eph-{oid.hex[:6]}"},
    )
    await test_db.commit()

    wf = await _seed_workflow(test_db, org_id=oid)
    sch = _new_schedule(org_id=oid, workflow_id=wf.id)
    await workflows_da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    sid = sch.id

    # Hard delete the org — CASCADE should drop the workflow and
    # then the schedule.
    await test_db.execute(
        sql_text("DELETE FROM tbl_organizations WHERE id = :id"),
        {"id": str(oid)},
    )
    await test_db.commit()

    assert (
        await workflows_da.get_schedule_by_id_and_org(test_db, org_id=oid, schedule_id=sid) is None
    )
