"""Bus → engine bridge for the workflows module.

Registers one universal handler (:func:`_on_event`) against every
event type in :mod:`core.events.event_catalog`. On every published
event the handler walks the org's ``active`` workflows whose
``enabled_event_types`` includes the event type, evaluates the
re-enrollment rule, and calls :func:`core.workflows.engine.start_run`
for each match.

Subscriber registration happens at module import time via
:func:`register_subscribers` — see :mod:`core.workflows.__init__`
for the side-effect import.

Per-event-type dispatch via the bus means the subscriber count
stays constant (~30 events) regardless of how many workflows the
org has defined. The matcher's array filter on
``enabled_event_types`` then narrows from "every active workflow"
to "every active workflow that listens on this event" in one
indexed SQL hit per published event.

Re-enrollment rules:

  * ``once``: refuse start_run when any prior non-canceled run
    exists for ``(workflow_id, contact_id)``. Captures the
    "enroll the contact at most once, ever" semantics.
  * ``daily``: refuse when a prior non-canceled run started on or
    after today's UTC midnight for ``(workflow_id, contact_id)``.
  * ``never``: always allow.

Idempotency:

  When the envelope carries ``event_id``, the handler checks for a
  prior run with the same ``(workflow_id, trigger_event_id)`` pair
  BEFORE the re-enrollment check. Replays of the same event get
  refused regardless of re-enrollment rule.

A/B sibling split:

  When the matched workflow has ``ab_sibling_id`` set,
  :func:`_split_for_ab` would 50/50-split the enrolment between
  the two siblings. v1 (Step 5) returns the workflow unchanged;
  Step 18 wires the actual split.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.events import bus as events_bus
from src.app.core.events.conditions import evaluate_safe
from src.app.core.events.event_catalog import ALL_EVENTS
from src.app.core.workflows import data_access as _da
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
)

logger = logging.getLogger(__name__)


async def _on_event(envelope: dict[str, Any]) -> None:
    """Universal handler — fans every published event into the
    workflow matcher + engine.

    The envelope carries:
      * ``event_type``  — the published event-type string.
      * ``org_id``      — tenant scope. Required.
      * ``event_id``    — publisher-supplied idempotency key.
      * ``contact_id``  — optional. When set, runs enrol the named
                          contact; when absent, runs enrol with
                          ``contact_id=NULL`` (e.g. ``time.daily_tick``).

    Failure mode: any exception inside this handler is logged but
    NOT re-raised — the bus already swallows handler exceptions to
    isolate one bad subscriber from the rest, but we log per-handler
    so the operator can investigate via the run-history UI."""
    from src.app.shared.context import (
        RequestContext,
        reset_context,
        set_context,
    )
    from src.app.shared.db import async_session

    event_type = envelope.get("event_type")
    org_id = envelope.get("org_id")
    if not event_type or org_id is None:
        # Defensive — the bus envelope guarantees these, but we
        # don't crash on a malformed publish.
        logger.warning(
            "workflows._on_event missing_envelope_fields event_type=%r org_id=%r",
            event_type,
            org_id,
        )
        return

    if not isinstance(org_id, uuid.UUID):
        try:
            org_id = uuid.UUID(str(org_id))
        except (ValueError, TypeError):
            logger.warning("workflows._on_event malformed_org_id org_id=%r", org_id)
            return

    contact_id_raw = envelope.get("contact_id")
    contact_id: uuid.UUID | None = None
    if contact_id_raw is not None:
        try:
            contact_id = uuid.UUID(str(contact_id_raw))
        except (ValueError, TypeError):
            contact_id = None

    event_id = envelope.get("event_id")
    event_id_str = str(event_id) if event_id is not None else None

    async with async_session() as session:
        token = set_context(RequestContext(org_id=org_id, user_id=None))
        try:
            workflows = await _da.list_active_workflows_for_event(
                session, org_id=org_id, event_type=event_type
            )
            # Step 11 — also resume any parked wait_for_event nodes
            # whose event_type + contact_id matches this publish.
            # Runs on every event, independent of the trigger-match
            # path; one event may both start new runs AND resume
            # existing ones for different workflows.
            await _resume_matching_waits(
                session,
                org_id=org_id,
                event_type=event_type,
                contact_id=contact_id,
            )
        finally:
            reset_context(token)

        if not workflows:
            return

        # Build the trigger payload — strip the bus's envelope keys
        # and pass the rest as the run's trigger_payload. We keep
        # ``contact_id`` + ``event_id`` in the payload too so the
        # action handlers can reference them via variable resolution.
        trigger_payload = {k: v for k, v in envelope.items() if k not in ("event_type", "org_id")}

        for workflow in workflows:
            try:
                # Step 6 — evaluate the trigger node's conditions
                # against the published envelope BEFORE any DB writes
                # land. A False verdict → log the rejection + skip
                # enrolment. No run row + no step_run row is created
                # (the spec's "audit row in step_runs" breadcrumb
                # would require a schema change since step_runs.run_id
                # is NOT NULL; the v1 surface is the log line, the
                # Step-19 diagnostics view will lift it when ready).
                if not _trigger_conditions_match(workflow, trigger_payload):
                    logger.info(
                        "workflows._on_event condition_failed org=%s "
                        "workflow=%s event=%s contact=%s",
                        org_id,
                        workflow.id,
                        event_type,
                        contact_id,
                    )
                    continue

                effective_workflow = await _split_for_ab(
                    session, workflow=workflow, contact_id=contact_id
                )
                await _maybe_start_run(
                    session,
                    workflow=effective_workflow,
                    contact_id=contact_id,
                    trigger_event_id=event_id_str,
                    trigger_payload=trigger_payload,
                )
            except Exception:
                logger.exception(
                    "workflows._on_event start_run_failed org=%s workflow=%s event=%s",
                    org_id,
                    workflow.id,
                    event_type,
                )


async def _maybe_start_run(
    session,
    *,
    workflow: Workflow,
    contact_id: uuid.UUID | None,
    trigger_event_id: str | None,
    trigger_payload: dict[str, Any],
) -> None:
    """Re-enrollment + idempotency gate. Calls
    :func:`core.workflows.engine.start_run` when the gate opens;
    otherwise logs the refusal at INFO so operators can trace
    "why didn't my workflow fire?" via the Step 19 diagnostics
    surface."""
    from src.app.core.workflows import engine

    # 1) Idempotency on (workflow_id, trigger_event_id) — replays
    # of the same publish drop here. Wins over re-enrollment
    # because publishers usually re-publish on retries.
    if trigger_event_id is not None:
        existing = await _da.find_existing_run(
            session,
            workflow_id=workflow.id,
            contact_id=contact_id,
            trigger_event_id=trigger_event_id,
        )
        if existing is not None:
            logger.info(
                "workflows._maybe_start_run dedupe_replay workflow=%s event_id=%s",
                workflow.id,
                trigger_event_id,
            )
            return

    # 2) Re-enrollment rule. Skipped entirely when contact_id is
    # None — workflows with no contact dimension (time.daily_tick)
    # always create a fresh run.
    if contact_id is not None:
        rule = workflow.re_enrollment_rule
        if rule == WorkflowReEnrollmentRule.once:
            existing = await _da.find_existing_run(
                session,
                workflow_id=workflow.id,
                contact_id=contact_id,
            )
            if existing is not None:
                logger.info(
                    "workflows._maybe_start_run dedupe_once workflow=%s contact=%s",
                    workflow.id,
                    contact_id,
                )
                return
        elif rule == WorkflowReEnrollmentRule.daily:
            today_utc_midnight = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            existing = await _da.find_existing_run(
                session,
                workflow_id=workflow.id,
                contact_id=contact_id,
                since_started_at=today_utc_midnight,
            )
            if existing is not None:
                logger.info(
                    "workflows._maybe_start_run dedupe_daily workflow=%s contact=%s",
                    workflow.id,
                    contact_id,
                )
                return
        # WorkflowReEnrollmentRule.never falls through to start_run.

    await engine.start_run(
        session,
        workflow=workflow,
        contact_id=contact_id,
        trigger_event_id=trigger_event_id,
        trigger_payload=trigger_payload,
    )


def _trigger_conditions_match(workflow: Workflow, payload: dict[str, Any]) -> bool:
    """Step 6 — evaluate the trigger node's ``config.conditions``
    against the published envelope. Empty / missing conditions
    evaluate to True (the "always match" default for fresh
    workflows + the seeded defaults). Malformed conditions
    evaluate to False via ``evaluate_safe`` — one bad workflow
    can't poison every event publish."""
    graph = workflow.graph or {}
    nodes = graph.get("nodes") or []
    trigger_node = next(
        (n for n in nodes if str(n.get("type", "")).startswith("trigger")),
        None,
    )
    if trigger_node is None:
        # Defensive — should be caught at validation time, but if a
        # workflow somehow loses its trigger we fail closed.
        return False

    conditions = (trigger_node.get("config") or {}).get("conditions")
    if conditions is None or conditions == {}:
        return True
    return evaluate_safe(conditions, payload)


async def _split_for_ab(
    session: AsyncSession,
    *,
    workflow: Workflow,
    contact_id: uuid.UUID | None,
) -> Workflow:
    """A/B sibling split — delegates to
    :func:`core.workflows.ab_testing.enroll_with_ab_split`.

    Step 18 wires the real deterministic split: when the workflow is
    paired (``ab_paired_workflow_id`` set), the contact is hashed
    against the pair key to pick A or B; otherwise the workflow is
    returned unchanged.
    """
    from src.app.core.workflows.ab_testing import enroll_with_ab_split

    return await enroll_with_ab_split(
        session, workflow=workflow, contact_id=contact_id
    )


def register_subscribers() -> None:
    """Subscribe :func:`_on_event` to every event in the catalog.
    Idempotent — re-running the registration is a no-op via the
    bus's idempotency check on ``(event_type, handler)``."""
    for event_type in ALL_EVENTS:
        events_bus.subscribe(event_type, _on_event)
    logger.info(
        "workflows.trigger_handlers registered handler for %d events",
        len(ALL_EVENTS),
    )


def unregister_subscribers() -> None:
    """Test helper — drop every subscription. Production never
    calls this; subscribers register at app-start and stay
    registered for the process lifetime."""
    for event_type in ALL_EVENTS:
        events_bus.unsubscribe(event_type, _on_event)


async def _resume_matching_waits(
    session,
    *,
    org_id: uuid.UUID,
    event_type: str,
    contact_id: uuid.UUID | None,
) -> None:
    """Step 11 — find every parked ``flow_control.wait_for_event``
    node whose event_type + contact_id matches the incoming event +
    resume the run on the ``event_received`` outbound edge.

    The DAL's ``find_waits_for_event`` already filters out expired
    waits via the partial index — so a hair-late event whose
    ``expires_at`` already lapsed won't double-fire alongside the
    beat sweep's timeout path. The sweep handles that wait
    exclusively.
    """
    from datetime import datetime

    from src.app.core.workflows import engine as workflows_engine

    now = datetime.now(UTC)
    matches = await _da.find_waits_for_event(
        session,
        org_id=org_id,
        event_type=event_type,
        contact_id=contact_id,
        now=now,
    )

    for wait in matches:
        try:
            # Delete the wait FIRST so a concurrent event publish
            # doesn't double-resume the same run.
            await _da.delete_event_wait(session, wait)
            await session.commit()
        except Exception:
            logger.exception(
                "workflows._resume_matching_waits delete_failed wait=%s",
                wait.id,
            )
            continue
        try:
            await workflows_engine.resume_run(wait.run_id, output_edge_label="event_received")
        except Exception:
            logger.exception(
                "workflows._resume_matching_waits resume_failed wait=%s run=%s",
                wait.id,
                wait.run_id,
            )


__all__ = [
    "register_subscribers",
    "unregister_subscribers",
]
