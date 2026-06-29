"""Workflow execution engine.

Three public entry points + one driver helper:

  * :func:`start_run` — invoked by the Step-5 trigger handlers. Inserts
    a run row in ``status='pending'`` pointed at the trigger node + enqueues
    the first :func:`process_step` Celery dispatch.
  * :func:`process_step` — Celery task body. Loads the run (with row-level
    ``FOR UPDATE SKIP LOCKED`` so two workers can't process the same run
    in parallel), resolves the current node's action handler, runs it,
    persists a step_run audit row, then advances to the next node.
    Recursion happens via Celery enqueue, never inline — Celery's
    scheduler-latency budgets the per-hop tail-latency.
  * :func:`resume_after_wait` — beat-driven sweep. Pulls runs whose
    ``next_step_at <= now()`` and re-dispatches :func:`process_step` so
    parked wait nodes resume.

Wait-node mechanics (v1):

  When the engine advances TO a node whose type is in :data:`_WAIT_TYPES`,
  it sets ``run.next_step_at = now + delay_seconds`` (read from
  ``node.config.delay_seconds`` or, when absent, ``max_wait_seconds``)
  and leaves ``status='pending'``. The beat sweep picks the run up
  later; the next ``process_step`` execution treats the wait node as
  completed and walks past it. Step 11 will refine this with a proper
  ``flow.wait`` handler that emits its own ``ActionResult`` — for now
  the engine handles the parking inline.

Trigger-node mechanics:

  Trigger nodes (type prefix ``trigger.``) resolve to the single
  registered ``trigger`` handler from :mod:`core.workflows.actions`.
  The handler is a no-op that just records the enrollment; the actual
  event-payload extraction happens during ``start_run``.

Goal-node terminal handling:

  When the executed node's id matches ``workflow.goal_node_id`` AND has
  no outbound edges, the run terminates with ``outcome='goal_reached'``.
  Otherwise no-outbound terminates with ``outcome='completed'``.

Error policy:

  Any exception from an action handler is caught, the traceback message
  written to ``step_run.error``, and the run set to ``status='errored'``
  with ``outcome='errored'``. Step 19 surfaces the failure on the
  run-history UI. Retry / DLQ policies are deferred per the Step-4
  spec; v1 errors are terminal.

Clock-skew note:

  Celery ``eta`` for waits has worker-clock skew implications — under
  heavy load a 60s wait could fire 60-90s late. Acceptable for the
  marketing-nurture use cases this engine targets; if sub-second
  precision is ever required, swap the Celery enqueue for a tight
  asyncio.sleep + same-worker continuation (much higher ops cost).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import data_access as _da
from src.app.core.workflows.actions import (
    ActionNotRegistered,
    is_registered,
    resolve as resolve_action,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepRunStatus,
)


logger = logging.getLogger(__name__)


# Node-type prefixes the engine recognises for routing.
_TRIGGER_PREFIX = "trigger"
_WAIT_TYPES = frozenset({"flow.wait", "flow.wait_for_event"})

# Status set that means "engine should not advance this run further".
_TERMINAL_STATUSES = frozenset(
    {
        WorkflowRunStatus.completed,
        WorkflowRunStatus.canceled,
        WorkflowRunStatus.errored,
    }
)


# --- Action handler contract ---------------------------------------------


@dataclass(slots=True)
class ActionResult:
    """Returned by an action handler. The engine reads this to decide
    how to advance:

      * ``next_edge_label`` — when the node has multiple outbound edges
        (branch / switch / ab-split), the engine matches by edge
        ``label`` to pick the next node. ``None`` means "follow the
        single outbound edge", or terminate when there are zero.
      * ``output`` — variables to merge into ``run.state`` for
        downstream nodes' variable resolution.
      * ``skip_reason`` — when non-None, the step is recorded with
        ``status='skipped'`` + ``skip_reason=…`` instead of
        ``status='completed'``. Compliance gates (Step 12) use this to
        record DPDP / quiet-hours / frequency-cap rejections.
    """

    next_edge_label: str | None = None
    output: dict[str, Any] | None = None
    skip_reason: str | None = None


#: Async handler signature: ``handle(session, *, run, step_run, node,
#: context) -> ActionResult``. Steps 7-11 register concrete handlers.
ActionHandler = Callable[..., Awaitable[ActionResult]]


# --- start_run ----------------------------------------------------------


async def start_run(
    session: AsyncSession,
    *,
    workflow: Workflow,
    contact_id: uuid.UUID | None,
    trigger_event_id: str | None,
    trigger_payload: dict[str, Any] | None = None,
) -> WorkflowRun:
    """Enrol a contact into a workflow. Inserts the run row pointed
    at the trigger node + enqueues the first :func:`process_step`
    Celery dispatch.

    Raises :class:`ValueError` when the workflow's graph has no
    trigger node (the Step-2 validator should have caught this on
    publish; we double-check defensively)."""
    graph = workflow.graph or {}
    nodes = graph.get("nodes") or []
    trigger_node = next(
        (n for n in nodes if str(n.get("type", "")).startswith(_TRIGGER_PREFIX)),
        None,
    )
    if trigger_node is None:
        raise ValueError(
            f"workflow {workflow.id} has no trigger node — refusing to start"
        )

    run = WorkflowRun(
        org_id=workflow.org_id,
        workflow_id=workflow.id,
        version=workflow.current_version,
        contact_id=contact_id,
        trigger_event_id=trigger_event_id,
        trigger_payload=trigger_payload or {},
        status=WorkflowRunStatus.pending,
        current_node_id=trigger_node["id"],
        state={},
    )
    _da.insert_run(session, run)
    await session.commit()
    await session.refresh(run)

    _schedule_process_step(run.id)
    logger.info(
        "workflows.engine.start_run org=%s workflow=%s run=%s contact=%s "
        "trigger_node=%s",
        workflow.org_id,
        workflow.id,
        run.id,
        contact_id,
        trigger_node["id"],
    )
    return run


# --- process_step --------------------------------------------------------


async def process_step(run_id: uuid.UUID) -> dict[str, Any]:
    """Celery-task body. Loads the run (locked) + workflow + current
    node, runs the action handler, persists a step_run audit row,
    advances the run. Re-enqueues :func:`process_step` for the next
    hop unless the next node is a wait (parked) or the run terminates.

    Safe to call against a missing / already-terminal run — the lock
    short-circuits cleanly.
    """
    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    async with async_session() as session:
        run = await _da.get_run_for_processing(session, run_id=run_id)
        if run is None:
            logger.info(
                "workflows.engine.process_step missing_or_locked run_id=%s",
                run_id,
            )
            return {"status": "skipped_or_locked"}
        if run.status in _TERMINAL_STATUSES:
            logger.info(
                "workflows.engine.process_step already_terminal run=%s status=%s",
                run.id,
                run.status.value,
            )
            return {"status": run.status.value}

        token = set_context(RequestContext(org_id=run.org_id, user_id=None))
        try:
            # Flip to running + release the FOR UPDATE lock by
            # committing. Subsequent handler work runs on a fresh
            # acquisition path.
            run.status = WorkflowRunStatus.running
            await session.commit()
            await session.refresh(run)

            return await _execute_current_node(session, run)
        finally:
            reset_context(token)


async def _execute_current_node(
    session: AsyncSession, run: WorkflowRun
) -> dict[str, Any]:
    """Hot path. Loads the workflow, picks the current node, runs
    the action handler, persists the step_run + run outcome, then
    either parks (wait) / terminates / advances."""
    workflow = await _da.get_workflow(
        session, org_id=run.org_id, workflow_id=run.workflow_id
    )
    if workflow is None:
        _mark_run_errored(run, error="workflow not found")
        await session.commit()
        return {"status": "errored", "reason": "workflow_missing"}

    # If the operator archived the workflow mid-run, terminate the
    # run as canceled rather than continuing under the old graph.
    if workflow.status == WorkflowStatus.archived:
        run.status = WorkflowRunStatus.canceled
        run.outcome = WorkflowRunOutcome.canceled
        run.current_node_id = None
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "canceled", "reason": "workflow_archived"}

    nodes_by_id = workflow.graph_nodes_by_id
    if run.current_node_id is None or run.current_node_id not in nodes_by_id:
        _mark_run_errored(
            run,
            error=f"current_node '{run.current_node_id}' not in graph",
        )
        await session.commit()
        return {"status": "errored", "reason": "node_missing"}

    node = nodes_by_id[run.current_node_id]

    # Allocate the next step_index + write the running step_run row.
    step_index = await _da.next_step_index(session, run_id=run.id)
    step_run = WorkflowStepRun(
        org_id=run.org_id,
        run_id=run.id,
        node_id=run.current_node_id,
        step_index=step_index,
        status=WorkflowStepRunStatus.running,
        payload=node.get("config") or {},
    )
    _da.insert_step_run(session, step_run)
    await session.commit()
    await session.refresh(step_run)

    # Resolve + execute the action handler.
    try:
        handler = _resolve_handler_for_node(node)
        context = await _build_handler_context(session, run)
        result = await handler(
            session,
            run=run,
            step_run=step_run,
            node=node,
            context=context,
        )
    except ActionNotRegistered as exc:
        return await _finalize_step_error(
            session, run=run, step_run=step_run, error=str(exc)
        )
    except Exception as exc:
        return await _finalize_step_error(
            session, run=run, step_run=step_run, error=str(exc)
        )

    # Persist step outcome.
    if result.skip_reason:
        step_run.status = WorkflowStepRunStatus.skipped
        step_run.skip_reason = result.skip_reason
    else:
        step_run.status = WorkflowStepRunStatus.completed
    step_run.output_edge_label = result.next_edge_label
    step_run.completed_at = datetime.now(timezone.utc)

    # Merge handler output into run.state for downstream variable
    # resolution.
    if result.output:
        merged = dict(run.state or {})
        merged.update(result.output)
        run.state = merged

    await _advance(
        session,
        workflow=workflow,
        run=run,
        nodes_by_id=nodes_by_id,
        output_edge_label=result.next_edge_label,
    )
    return {"status": run.status.value}


async def _finalize_step_error(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    error: str,
) -> dict[str, Any]:
    """Common error-path: write the failure to both rows + terminate
    the run."""
    step_run.status = WorkflowStepRunStatus.errored
    step_run.error = error
    step_run.completed_at = datetime.now(timezone.utc)
    _mark_run_errored(run, error=error)
    await session.commit()
    logger.warning(
        "workflows.engine step_errored run=%s node=%s error=%s",
        run.id,
        run.current_node_id,
        error,
    )
    return {"status": "errored", "reason": error}


def _mark_run_errored(run: WorkflowRun, *, error: str) -> None:
    run.status = WorkflowRunStatus.errored
    run.outcome = WorkflowRunOutcome.errored
    run.error = error
    run.completed_at = datetime.now(timezone.utc)


def _resolve_handler_for_node(node: dict[str, Any]) -> ActionHandler:
    """Pick the action handler for a node.

    Trigger nodes (any ``trigger.*`` type) share the single registered
    ``trigger`` handler — operators don't register per-event triggers
    individually. Wait + flow nodes share the built-in pass-through
    handlers registered at module import. Everything else dispatches
    on the literal ``node['type']``.
    """
    node_type = str(node.get("type") or "")
    if node_type.startswith(_TRIGGER_PREFIX + ".") or node_type == _TRIGGER_PREFIX:
        return resolve_action("trigger")
    # Wait nodes get a built-in no-op pass-through; the engine
    # post-process step recognises the wait + parks the run.
    if node_type in _WAIT_TYPES and not is_registered(node_type):
        return resolve_action("flow.wait")
    return resolve_action(node_type)


async def _build_handler_context(
    session: AsyncSession, run: WorkflowRun
) -> dict[str, Any]:
    """Context dict passed to every action handler. Steps 7-11 read
    ``contact`` / ``trigger_payload`` / ``run_state`` from here to
    render variables."""
    contact_dict: dict[str, Any] | None = None
    if run.contact_id is not None:
        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact

        contact = (
            await session.execute(
                _select(Contact).where(Contact.id == run.contact_id)
            )
        ).scalar_one_or_none()
        if contact is not None:
            contact_dict = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
    return {
        "contact": contact_dict,
        "trigger_payload": run.trigger_payload or {},
        "run_state": run.state or {},
    }


# --- _advance -----------------------------------------------------------


async def _advance(
    session: AsyncSession,
    *,
    workflow: Workflow,
    run: WorkflowRun,
    nodes_by_id: dict[str, dict[str, Any]],
    output_edge_label: str | None,
) -> None:
    """Pick the next node + persist the transition.

    Routing rules:

      * If the executed node has an ``output_edge_label`` (branch /
        switch / ab_split), pick the outbound edge whose ``label``
        matches. No matching edge → terminate (treats unmatched
        branches as run-end).
      * Else if there's exactly one outbound edge, follow it
        (sequential path).
      * Else if there are multiple unlabeled outbound edges, follow
        the first deterministically (operator's edge insertion order
        becomes the de facto priority).
      * Else (no outbound edges) → terminate. Set outcome to
        ``goal_reached`` when the executed node IS the workflow's
        goal node, otherwise ``completed``.

    Wait-node parking: when the chosen NEXT node is a wait, set
    ``run.next_step_at = now + delay_seconds`` and leave
    ``status='pending'`` so the beat sweep picks it up later. No
    Celery enqueue from here for the wait path.
    """
    edges = (workflow.graph or {}).get("edges") or []
    outbound = [
        e for e in edges if e.get("source") == run.current_node_id
    ]

    next_node_id: str | None = None
    if output_edge_label is not None:
        matching = [e for e in outbound if e.get("label") == output_edge_label]
        if matching:
            next_node_id = matching[0].get("target")
    elif outbound:
        next_node_id = outbound[0].get("target")

    if next_node_id is None or next_node_id not in nodes_by_id:
        # Terminal — workflow ends here.
        is_goal = (
            workflow.goal_node_id is not None
            and workflow.goal_node_id == run.current_node_id
        )
        run.status = WorkflowRunStatus.completed
        run.outcome = (
            WorkflowRunOutcome.goal_reached
            if is_goal
            else WorkflowRunOutcome.completed
        )
        run.completed_at = datetime.now(timezone.utc)
        run.current_node_id = None
        run.next_step_at = None
        await session.commit()
        return

    next_node = nodes_by_id[next_node_id]
    next_type = str(next_node.get("type") or "")

    # Park on wait nodes — the beat sweep will resume.
    if next_type in _WAIT_TYPES:
        delay_seconds = _extract_wait_seconds(next_node)
        run.current_node_id = next_node_id
        run.next_step_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay_seconds
        )
        run.status = WorkflowRunStatus.pending
        await session.commit()
        return

    # Normal hop — advance + re-enqueue the next step via Celery.
    run.current_node_id = next_node_id
    run.next_step_at = None
    run.status = WorkflowRunStatus.pending
    await session.commit()
    _schedule_process_step(run.id)


def _extract_wait_seconds(node: dict[str, Any]) -> int:
    """Read the wait duration from a wait node's config. Honours
    ``delay_seconds`` first, then ``max_wait_seconds`` (the latter is
    used by ``flow.wait_for_event`` where the wait is bounded by an
    event but capped). Defaults to 60s if both are absent — the
    validator should have rejected those, but the engine defends."""
    cfg = node.get("config") or {}
    for key in ("delay_seconds", "max_wait_seconds"):
        value = cfg.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return 60


# --- resume_after_wait --------------------------------------------------


async def resume_after_wait(now: datetime | None = None) -> dict[str, int]:
    """Beat-driven sweep. Pulls pending runs whose ``next_step_at <=
    now()`` and re-dispatches :func:`process_step` for each. The
    Celery task body in :mod:`core.workflows.tasks` calls this on the
    60s cadence wired in ``celery_config.beat_schedule``.

    Cross-tenant — opens a session WITHOUT setting
    ``RequestContext.org_id`` so the partial index sweep returns
    every tenant's due runs in one pass.
    """
    from src.app.shared.db import async_session

    now = now or datetime.now(timezone.utc)
    dispatched = 0

    async with async_session() as session:
        rows = await _da.list_runs_due_for_resume(
            session, now=now, limit=200
        )
        for run in rows:
            _schedule_process_step(run.id)
            dispatched += 1

    logger.info(
        "workflows.engine.resume_after_wait found=%d dispatched=%d",
        len(rows),
        dispatched,
    )
    return {"found": len(rows), "dispatched": dispatched}


# --- Celery enqueue helpers ---------------------------------------------


def _schedule_process_step(run_id: uuid.UUID) -> None:
    """Fire-and-forget Celery enqueue. Imported lazily so the engine
    can be unit-tested without Celery; the import goes through the
    shim in :mod:`core.workflows.tasks` so dev shells without
    Celery installed don't break."""
    from src.app.core.workflows import tasks as _tasks

    try:
        _tasks.process_step.apply_async(args=(str(run_id),), countdown=0)
    except Exception:
        logger.exception(
            "workflows.engine.schedule_process_step failed run_id=%s",
            run_id,
        )


__all__ = [
    "ActionHandler",
    "ActionResult",
    "process_step",
    "resume_after_wait",
    "start_run",
]
