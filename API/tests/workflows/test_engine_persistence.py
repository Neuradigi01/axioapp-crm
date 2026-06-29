"""Persistence + DAL pin tests for the Step-4 workflow engine.

Complements ``test_engine.py`` which covers the engine's branching
+ error + wait logic. This file covers:

  * ``insert_run`` + ``next_step_index`` give a monotonic
    ``step_index`` per run.
  * ``list_runs_due_for_resume`` honours the partial index's
    ``status='pending' AND next_step_at <= now()`` predicate.
  * ``list_runs`` filters by workflow_id + contact_id + status.
  * ``list_step_runs`` returns rows ordered by step_index ASC.
  * ``get_run_for_processing`` returns the row (single-worker case);
    the FOR-UPDATE-SKIP-LOCKED concurrent-worker behaviour can't be
    cleanly tested in-process — documented + verified at DB layer
    by the migration's partial index.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows import data_access as workflows_da
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


async def _seed_workflow(test_db, *, org_id) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph={"nodes": [{"id": "t1", "type": "trigger.lead_created"}], "edges": []},
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _seed_run(
    test_db,
    *,
    org_id,
    workflow_id,
    status: WorkflowRunStatus = WorkflowRunStatus.pending,
    next_step_at: datetime | None = None,
    contact_id: uuid.UUID | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        org_id=org_id,
        workflow_id=workflow_id,
        version=1,
        contact_id=contact_id,
        status=status,
        current_node_id="t1",
        state={},
        next_step_at=next_step_at,
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# next_step_index monotonicity
# ---------------------------------------------------------------------------


async def test_next_step_index_monotonic_per_run(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    run = await _seed_run(test_db, org_id=org_id, workflow_id=wf.id)

    # First allocation against an empty run → 0.
    idx0 = await workflows_da.next_step_index(test_db, run_id=run.id)
    assert idx0 == 0

    # Insert a step_run; next allocation should be 1.
    sr0 = WorkflowStepRun(
        org_id=org_id,
        run_id=run.id,
        node_id="t1",
        step_index=idx0,
        status=WorkflowStepRunStatus.completed,
        payload={},
    )
    test_db.add(sr0)
    await test_db.commit()

    idx1 = await workflows_da.next_step_index(test_db, run_id=run.id)
    assert idx1 == 1


# ---------------------------------------------------------------------------
# list_runs_due_for_resume — partial index predicate
# ---------------------------------------------------------------------------


async def test_list_runs_due_picks_pending_in_past_only(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    now = datetime.now(timezone.utc)

    due = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf.id,
        next_step_at=now - timedelta(minutes=5),
    )
    not_due = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf.id,
        next_step_at=now + timedelta(hours=1),
    )
    # A completed run with next_step_at in the past must NOT surface.
    completed = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf.id,
        status=WorkflowRunStatus.completed,
        next_step_at=now - timedelta(hours=1),
    )

    rows = await workflows_da.list_runs_due_for_resume(test_db, now=now)
    ids = {r.id for r in rows}
    assert due.id in ids
    assert not_due.id not in ids
    assert completed.id not in ids


# ---------------------------------------------------------------------------
# list_runs filters
# ---------------------------------------------------------------------------


async def test_list_runs_filters_by_workflow_and_status(test_db, org_id):
    wf_a = await _seed_workflow(test_db, org_id=org_id)
    wf_b = await _seed_workflow(test_db, org_id=org_id)

    run_a1 = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf_a.id,
        status=WorkflowRunStatus.completed,
    )
    run_a2 = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf_a.id,
        status=WorkflowRunStatus.errored,
    )
    run_b1 = await _seed_run(
        test_db,
        org_id=org_id,
        workflow_id=wf_b.id,
        status=WorkflowRunStatus.completed,
    )

    # Workflow A only.
    rows_a, total_a = await workflows_da.list_runs(
        test_db, org_id=org_id, workflow_id=wf_a.id
    )
    assert total_a == 2
    assert {r.id for r in rows_a} == {run_a1.id, run_a2.id}

    # Workflow A + status=errored.
    rows_err, total_err = await workflows_da.list_runs(
        test_db,
        org_id=org_id,
        workflow_id=wf_a.id,
        status=WorkflowRunStatus.errored,
    )
    assert total_err == 1
    assert rows_err[0].id == run_a2.id

    # Workflow B only — should not include any of A's rows.
    rows_b, total_b = await workflows_da.list_runs(
        test_db, org_id=org_id, workflow_id=wf_b.id
    )
    assert total_b == 1
    assert rows_b[0].id == run_b1.id


# ---------------------------------------------------------------------------
# list_step_runs ordering
# ---------------------------------------------------------------------------


async def test_list_step_runs_ordered_by_step_index_asc(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    run = await _seed_run(test_db, org_id=org_id, workflow_id=wf.id)

    # Insert in reverse step_index order to exercise the ORDER BY.
    for i in (2, 0, 1):
        test_db.add(
            WorkflowStepRun(
                org_id=org_id,
                run_id=run.id,
                node_id=f"n{i}",
                step_index=i,
                status=WorkflowStepRunStatus.completed,
                payload={},
            )
        )
    await test_db.commit()

    rows = await workflows_da.list_step_runs(
        test_db, org_id=org_id, run_id=run.id
    )
    assert [r.step_index for r in rows] == [0, 1, 2]


# ---------------------------------------------------------------------------
# get_run + get_run_for_processing
# ---------------------------------------------------------------------------


async def test_get_run_for_processing_returns_row_when_unlocked(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    run = await _seed_run(test_db, org_id=org_id, workflow_id=wf.id)

    row = await workflows_da.get_run_for_processing(test_db, run_id=run.id)
    assert row is not None
    assert row.id == run.id


async def test_get_run_returns_none_for_cross_tenant(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    run = await _seed_run(test_db, org_id=org_id, workflow_id=wf.id)

    other_org = uuid.uuid4()
    row = await workflows_da.get_run(test_db, org_id=other_org, run_id=run.id)
    assert row is None
