"""Pin tests for Step-14 workflow dry-run / test-fire support.

Covers:

  * ``engine.start_run(dry_run=True)`` returns a ``DryRunResult`` with
    one step per node walked + the synthetic outcome.
  * ``dry_run=True`` does NOT persist ``tbl_workflow_runs`` or
    ``tbl_workflow_step_runs`` rows, and does NOT schedule a Celery
    dispatch — the test-fire path is pure in-memory.

Action handlers are exercised through the dry-walk path which skips
them entirely; therefore no real send / record / routing handler is
needed in fixtures.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text as sql_text

from src.app.core.workflows import engine as workflows_engine
from src.app.core.workflows.engine import DryRunResult, DryRunStep
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepRun,
)
from src.app.shared.context import RequestContext, reset_context, set_context


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


async def _make_workflow(test_db, *, org_id) -> Workflow:
    """Trigger → send.email → end. A simple 3-node graph the dry walk
    will trace from start to terminal."""
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.draft,
        current_version=1,
        graph={
            "nodes": [
                {"id": "t1", "type": "trigger.lead_created", "config": {}},
                {"id": "s1", "type": "send.email", "config": {"template_id": "abc"}},
                {"id": "g1", "type": "flow_control.goal", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "t1", "target": "s1", "label": None},
                {"id": "e2", "source": "s1", "target": "g1", "label": None},
            ],
        },
        goal_node_id="g1",
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def test_start_run_dry_run_returns_trace_without_celery_dispatch(
    test_db, org_id
):
    """`start_run(dry_run=True)` returns a `DryRunResult` with a step
    per node visited and never schedules a Celery dispatch."""
    wf = await _make_workflow(test_db, org_id=org_id)

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(
            workflows_engine, "_schedule_process_step"
        ) as sched:
            result = await workflows_engine.start_run(
                test_db,
                workflow=wf,
                contact_id=None,
                trigger_event_id=None,
                trigger_payload={"lead_id": "x"},
                dry_run=True,
            )
    finally:
        reset_context(token)

    assert isinstance(result, DryRunResult)
    assert result.workflow_id == wf.id
    assert result.outcome == "goal_reached"
    assert result.error is None
    # One step per node (trigger, send, goal).
    assert [s.node_id for s in result.steps] == ["t1", "s1", "g1"]
    # First two steps record the outbound edge label (None for
    # sequential), last hop has no outbound edge.
    assert all(isinstance(s, DryRunStep) for s in result.steps)
    assert result.steps[-1].edge_label is None
    # Celery scheduler is the persistence side-effect we MUST NOT
    # trigger on a dry-run.
    sched.assert_not_called()


async def test_dry_run_does_not_persist_run_or_step_run_rows(
    test_db, org_id
):
    """`dry_run=True` is pure in-memory — no `tbl_workflow_runs` and
    no `tbl_workflow_step_runs` rows are written, regardless of how
    many nodes the dry-walk visits."""
    wf = await _make_workflow(test_db, org_id=org_id)

    runs_before = (
        await test_db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.workflow_id == wf.id
            )
        )
    ).scalar_one()
    step_runs_before = (
        await test_db.execute(
            select(func.count()).select_from(WorkflowStepRun)
        )
    ).scalar_one()

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.start_run(
                test_db,
                workflow=wf,
                contact_id=None,
                trigger_event_id=None,
                trigger_payload=None,
                dry_run=True,
            )
    finally:
        reset_context(token)

    runs_after = (
        await test_db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.workflow_id == wf.id
            )
        )
    ).scalar_one()
    step_runs_after = (
        await test_db.execute(
            select(func.count()).select_from(WorkflowStepRun)
        )
    ).scalar_one()

    assert runs_after == runs_before, (
        "test-fire must not insert tbl_workflow_runs rows"
    )
    assert step_runs_after == step_runs_before, (
        "test-fire must not insert tbl_workflow_step_runs rows"
    )
