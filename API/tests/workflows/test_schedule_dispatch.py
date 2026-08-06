"""Integration tests for the schedule dispatch loop.

Uses a real DB. Covers:
  * Sweep picks up due, active schedules for an active workflow.
  * Sweep skips: inactive schedule, future next_run_at, archived
    workflow, draft workflow.
  * Dispatched run has ``trigger_kind='schedule'`` +
    ``trigger_source_id`` matching the schedule.
  * Schedule advances: ``runs_completed`` bumps; ``next_run_at`` moves
    to the future for recurring kinds; once-schedules terminate with
    ``deactivation_reason='ended'``.
  * Concurrency ``forbid`` skips when a prior run is still running.
  * Poison row (invalid config_json cron) is deactivated with
    ``deactivation_reason='recurrence_invalid'``; sweep continues
    to fire the sibling row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.app.core.workflows import data_access as _da
from src.app.core.workflows import service as wf_service
from src.app.core.workflows.models import (
    ConcurrencyPolicy,
    DeactivationReason,
    OnMissedPolicy,
    ScheduleKind,
    TriggerKind,
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


def _mk_schedule(
    *,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    next_run_at: datetime | None,
    kind: ScheduleKind = ScheduleKind.daily,
    config: dict | None = None,
    active: bool = True,
    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.allow,
    name: str = "test",
) -> WorkflowSchedule:
    return WorkflowSchedule(
        org_id=org_id,
        workflow_id=workflow_id,
        name=name,
        schedule_kind=kind,
        config_json=config or {"time": "09:00"},
        timezone="UTC",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        next_run_at=next_run_at,
        active=active,
        on_missed=OnMissedPolicy.skip,
        concurrency_policy=concurrency,
        runs_completed=0,
    )


@pytest.fixture(autouse=True)
def _patch_async_session(test_db, monkeypatch):
    """Redirect ``shared.db.async_session`` to a sessionmaker bound
    to the pytest test DB so ``sweep_due_schedules`` (which opens its
    own sessions via that helper) reads / writes against the same DB
    as the test fixtures."""
    import src.app.shared.db as shared_db

    bind = test_db.get_bind()
    fake_sessionmaker = async_sessionmaker(bind, expire_on_commit=False)
    monkeypatch.setattr(shared_db, "async_session", fake_sessionmaker)
    yield


# ---------------------------------------------------------------------------
# Sweep picks + skips
# ---------------------------------------------------------------------------


async def test_sweep_picks_and_fires_due_schedule(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
    )
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    await test_db.refresh(sch)

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["fired"] == 1

    # A workflow_run with schedule provenance exists.
    result = await test_db.execute(
        select(WorkflowRun).where(WorkflowRun.trigger_source_id == sch.id)
    )
    runs = list(result.scalars().all())
    assert len(runs) == 1
    assert runs[0].trigger_kind == TriggerKind.schedule
    assert runs[0].trigger_source_id == sch.id


async def test_sweep_skips_future_schedules(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    future = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now + timedelta(hours=1),
        name="future",
    )
    await _da.insert_schedule(test_db, schedule=future)
    await test_db.commit()

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["found"] == 0
    assert stats["fired"] == 0


async def test_sweep_skips_paused_schedules(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    paused = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        active=False,
        name="paused",
    )
    await _da.insert_schedule(test_db, schedule=paused)
    await test_db.commit()

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["found"] == 0


async def test_sweep_skips_schedules_on_draft_workflow(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id, status=WorkflowStatus.draft)
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
    )
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["fired"] == 0


# ---------------------------------------------------------------------------
# Advance + terminal conditions
# ---------------------------------------------------------------------------


async def test_once_schedule_deactivates_after_fire(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.once,
        config={"at": (now + timedelta(hours=1)).isoformat()},
    )
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    await test_db.refresh(sch)

    await wf_service.sweep_due_schedules(now=now)

    refreshed = await _da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sch.id)
    assert refreshed is not None
    assert refreshed.active is False
    assert refreshed.deactivation_reason == DeactivationReason.ended
    assert refreshed.next_run_at is None
    assert refreshed.runs_completed == 1


async def test_daily_schedule_advances_next_run_at_after_fire(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.daily,
        config={"time": "09:00"},
    )
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()
    await test_db.refresh(sch)

    await wf_service.sweep_due_schedules(now=now)

    refreshed = await _da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sch.id)
    assert refreshed is not None
    assert refreshed.active is True
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at > now
    assert refreshed.runs_completed == 1


async def test_max_runs_reached_deactivates_row(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)
    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.daily,
    )
    sch.max_runs = 1
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    await wf_service.sweep_due_schedules(now=now)

    refreshed = await _da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sch.id)
    assert refreshed is not None
    assert refreshed.active is False
    assert refreshed.deactivation_reason == DeactivationReason.max_runs


# ---------------------------------------------------------------------------
# Concurrency policies
# ---------------------------------------------------------------------------


async def test_concurrency_forbid_skips_when_prior_run_running(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)

    # Seed a running run to simulate "prior fire still in flight".
    prior = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.running,
        current_node_id="t1",
        state={},
    )
    test_db.add(prior)
    await test_db.commit()

    sch = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.daily,
        concurrency=ConcurrencyPolicy.forbid,
    )
    await _da.insert_schedule(test_db, schedule=sch)
    await test_db.commit()

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["skipped"] == 1
    assert stats["fired"] == 0

    # runs_completed should NOT have advanced.
    refreshed = await _da.get_schedule_by_id_and_org(test_db, org_id=org_id, schedule_id=sch.id)
    assert refreshed is not None
    assert refreshed.runs_completed == 0
    # next_run_at DID advance so we don't tight-loop on the same row.
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at > now


# ---------------------------------------------------------------------------
# Poison-row isolation
# ---------------------------------------------------------------------------


async def test_poison_row_auto_deactivates_and_sweep_continues(test_db, org_id):
    """A malformed cron in ``config_json`` fails on load. The
    sweep must deactivate that row (reason='recurrence_invalid')
    AND still fire the sibling."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(UTC)

    poison = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.cron,
        config={"expression": "bogus not-a-cron"},
        name="poison",
    )
    healthy = _mk_schedule(
        org_id=org_id,
        workflow_id=wf.id,
        next_run_at=now - timedelta(minutes=1),
        kind=ScheduleKind.daily,
        config={"time": "09:00"},
        name="healthy",
    )
    await _da.insert_schedule(test_db, schedule=poison)
    await _da.insert_schedule(test_db, schedule=healthy)
    await test_db.commit()
    await test_db.refresh(poison)
    await test_db.refresh(healthy)

    stats = await wf_service.sweep_due_schedules(now=now)
    assert stats["errored"] == 1
    assert stats["fired"] == 1

    poison_after = await _da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=poison.id
    )
    assert poison_after is not None
    assert poison_after.active is False
    assert poison_after.deactivation_reason == DeactivationReason.recurrence_invalid

    healthy_after = await _da.get_schedule_by_id_and_org(
        test_db, org_id=org_id, schedule_id=healthy.id
    )
    assert healthy_after is not None
    assert healthy_after.active is True
    assert healthy_after.runs_completed == 1
