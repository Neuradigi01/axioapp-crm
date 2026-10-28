"""Pin tests for the Step-4 workflow execution engine.

Covers:

  * ``start_run`` inserts a run + sets ``current_node_id`` to the
    trigger node id.
  * ``process_step`` advances trigger → action → terminal cleanly.
  * Linear two-node workflow lands step_runs with monotonic
    step_index 0, 1.
  * Branch node with ``next_edge_label='yes'`` picks the yes edge.
  * Wait node parks the run with ``next_step_at`` set + status
    stays ``pending``.
  * ``resume_after_wait`` picks up due runs and dispatches.
  * Action handler raising terminates the run with status='errored'
    + step_run.error populated.
  * Goal node terminal sets ``outcome='goal_reached'``.
  * Unknown action_type lands the run as errored with
    ``ActionNotRegistered`` reason.

All Celery dispatches are mocked at the
:func:`core.workflows.engine._schedule_process_step` boundary so
no real workers are required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.workflows import engine as workflows_engine
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
    register_action,
)
from src.app.core.workflows.engine import ActionResult
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


@pytest.fixture(autouse=True)
def _reset_action_registry():
    """Wipe + restore the built-ins between cases so trigger /
    flow.wait / flow.end always resolve."""
    _clear_registry_for_tests()
    _register_builtins()
    yield
    _clear_registry_for_tests()
    _register_builtins()


async def _make_workflow(
    test_db,
    *,
    org_id,
    nodes: list[dict],
    edges: list[dict],
    goal_node_id: str | None = None,
    status: WorkflowStatus = WorkflowStatus.active,
) -> Workflow:
    """Insert a workflow row directly (bypassing the service +
    graph validator) so engine tests can build arbitrary graphs."""
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=status,
        current_version=1,
        graph={"nodes": nodes, "edges": edges},
        goal_node_id=goal_node_id,
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# start_run
# ---------------------------------------------------------------------------


async def test_start_run_inserts_pending_at_trigger_node(test_db, org_id):
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "end", "type": "flow.end", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "end"}],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step") as sched:
            run = await workflows_engine.start_run(
                test_db,
                workflow=wf,
                contact_id=None,
                trigger_event_id="lead_created:abc",
                trigger_payload={"lead_id": "x"},
            )
    finally:
        reset_context(token)

    assert run.status == WorkflowRunStatus.pending
    assert run.current_node_id == "t1"
    assert run.trigger_event_id == "lead_created:abc"
    sched.assert_called_once_with(run.id)


async def test_start_run_raises_when_no_trigger_in_graph(test_db, org_id):
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[{"id": "n1", "type": "send.email", "config": {}}],
        edges=[],
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(ValueError):
            await workflows_engine.start_run(
                test_db,
                workflow=wf,
                contact_id=None,
                trigger_event_id=None,
                trigger_payload=None,
            )
    finally:
        reset_context(token)


# ---------------------------------------------------------------------------
# process_step — linear advance
# ---------------------------------------------------------------------------


async def test_process_step_advances_trigger_to_terminal(test_db, org_id):
    """Linear trigger → end. The engine processes the trigger node,
    writes one step_run, and lands the run as completed because the
    next node (flow.end) has no outbound edges."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "end", "type": "flow.end", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "end"}],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step") as sched:
            run = await workflows_engine.start_run(
                test_db,
                workflow=wf,
                contact_id=None,
                trigger_event_id=None,
            )
    finally:
        reset_context(token)

    # First hop: trigger node. Engine re-schedules to advance to 'end'.
    with patch.object(workflows_engine, "_schedule_process_step") as sched:
        await workflows_engine.process_step(run.id)
    assert sched.called  # Re-enqueued the next hop.

    # Second hop: flow.end node. No outbound edges → terminal.
    with patch.object(workflows_engine, "_schedule_process_step") as sched:
        await workflows_engine.process_step(run.id)
    assert not sched.called

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.completed
    assert run.outcome == WorkflowRunOutcome.completed
    assert run.current_node_id is None


# ---------------------------------------------------------------------------
# Branch node — output_edge_label routing
# ---------------------------------------------------------------------------


async def test_branch_picks_labeled_edge(test_db, org_id):
    """A registered branch handler returning
    ``next_edge_label='yes'`` causes the engine to follow the
    matching outbound edge."""
    yes_landed = {"hit": False}
    no_landed = {"hit": False}

    async def branch_handler(session, *, run, step_run, node, context):
        return ActionResult(next_edge_label="yes")

    async def yes_handler(session, *, run, step_run, node, context):
        yes_landed["hit"] = True
        return ActionResult()

    async def no_handler(session, *, run, step_run, node, context):
        no_landed["hit"] = True
        return ActionResult()

    register_action("branch.if", lambda: branch_handler)
    register_action("send.yes", lambda: yes_handler)
    register_action("send.no", lambda: no_handler)

    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "br", "type": "branch.if", "config": {}},
            {"id": "y", "type": "send.yes", "config": {}},
            {"id": "n", "type": "send.no", "config": {}},
        ],
        edges=[
            {"id": "e1", "source": "t1", "target": "br"},
            {"id": "e2", "source": "br", "target": "y", "label": "yes"},
            {"id": "e3", "source": "br", "target": "n", "label": "no"},
        ],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )
        # Process the trigger → branch hop.
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
        # Process the branch → yes hop (the engine picks 'yes' label).
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
        # Process the 'send.yes' handler.
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
    finally:
        reset_context(token)

    assert yes_landed["hit"] is True
    assert no_landed["hit"] is False


# ---------------------------------------------------------------------------
# Wait node parking
# ---------------------------------------------------------------------------


async def test_wait_node_parks_run_without_recursing(test_db, org_id):
    """When the engine advances TO a wait node it sets
    ``next_step_at`` + leaves status='pending' + does NOT re-enqueue
    the Celery task — the beat sweep takes over."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {
                "id": "w1",
                "type": "flow.wait",
                "config": {"delay_seconds": 3600},
            },
            {"id": "end", "type": "flow.end", "config": {}},
        ],
        edges=[
            {"id": "e1", "source": "t1", "target": "w1"},
            {"id": "e2", "source": "w1", "target": "end"},
        ],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )
        # Trigger hop → engine should advance TO the wait node + park.
        with patch.object(workflows_engine, "_schedule_process_step") as sched:
            await workflows_engine.process_step(run.id)
            # Engine should NOT re-enqueue because the next node is a wait.
            assert not sched.called
    finally:
        reset_context(token)

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.pending
    assert run.current_node_id == "w1"
    assert run.next_step_at is not None
    # Should be ~1 hour ahead.
    delta = run.next_step_at - datetime.now(UTC)
    assert timedelta(minutes=58) < delta < timedelta(minutes=62)


# ---------------------------------------------------------------------------
# resume_after_wait sweep
# ---------------------------------------------------------------------------


async def test_resume_after_wait_dispatches_due_runs(test_db, org_id):
    """A pending run with ``next_step_at`` in the past lands in the
    sweep's dispatch list."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[{"id": "t1", "type": "trigger.lead_created", "config": {}}],
        edges=[],
    )
    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(hours=1)

    due = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        next_step_at=past,
    )
    not_due = WorkflowRun(
        org_id=org_id,
        workflow_id=wf.id,
        version=1,
        status=WorkflowRunStatus.pending,
        current_node_id="t1",
        state={},
        next_step_at=future,
    )
    test_db.add_all([due, not_due])
    await test_db.commit()
    await test_db.refresh(due)
    await test_db.refresh(not_due)

    with patch.object(workflows_engine, "_schedule_process_step") as sched:
        summary = await workflows_engine.resume_after_wait()

    assert summary["found"] >= 1
    dispatched_ids = {call.args[0] for call in sched.call_args_list}
    assert due.id in dispatched_ids
    assert not_due.id not in dispatched_ids


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_handler_exception_terminates_run_as_errored(test_db, org_id):
    """An action handler that raises lands the step_run as errored +
    the run as errored with the error message recorded."""

    async def broken_handler(session, *, run, step_run, node, context):
        raise RuntimeError("boom")

    register_action("send.broken", lambda: broken_handler)

    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "b", "type": "send.broken", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "b"}],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )
        # Trigger hop OK.
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
        # 'send.broken' hop raises → run errored.
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
    finally:
        reset_context(token)

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.errored
    assert run.outcome == WorkflowRunOutcome.errored
    assert "boom" in (run.error or "")

    step_runs = (
        (
            await test_db.execute(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.run_id == run.id)
                .order_by(WorkflowStepRun.step_index.asc())
            )
        )
        .scalars()
        .all()
    )
    errored = [s for s in step_runs if s.status == WorkflowStepRunStatus.errored]
    assert len(errored) == 1
    assert "boom" in (errored[0].error or "")


async def test_unknown_action_type_records_actionnotregistered(test_db, org_id):
    """A node whose action type isn't on the registry lands the run
    as errored with the ActionNotRegistered message."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "typo", "type": "send.does_not_exist", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "typo"}],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
    finally:
        reset_context(token)

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.errored
    assert "send.does_not_exist" in (run.error or "")


# ---------------------------------------------------------------------------
# Goal-node terminal handling
# ---------------------------------------------------------------------------


async def test_goal_node_terminal_sets_goal_reached(test_db, org_id):
    """Terminating on the goal node sets ``outcome='goal_reached'``."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "goal", "type": "flow.end", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "goal"}],
        goal_node_id="goal",
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
        with patch.object(workflows_engine, "_schedule_process_step"):
            await workflows_engine.process_step(run.id)
    finally:
        reset_context(token)

    await test_db.refresh(run)
    assert run.outcome == WorkflowRunOutcome.goal_reached


# ---------------------------------------------------------------------------
# Archived workflow → canceled run
# ---------------------------------------------------------------------------


async def test_archived_workflow_cancels_in_flight_run(test_db, org_id):
    """If the operator archives the workflow while a run is
    parked, the next process_step terminates the run as
    ``canceled`` rather than continuing under the old graph."""
    wf = await _make_workflow(
        test_db,
        org_id=org_id,
        nodes=[
            {"id": "t1", "type": "trigger.lead_created", "config": {}},
            {"id": "end", "type": "flow.end", "config": {}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "end"}],
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            run = await workflows_engine.start_run(
                test_db, workflow=wf, contact_id=None, trigger_event_id=None
            )

        # Archive the workflow before any process_step hops fire.
        wf.status = WorkflowStatus.archived
        await test_db.commit()

        with patch.object(workflows_engine, "_schedule_process_step") as sched:
            await workflows_engine.process_step(run.id)
            assert not sched.called
    finally:
        reset_context(token)

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.canceled
    assert run.outcome == WorkflowRunOutcome.canceled
