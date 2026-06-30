"""Workflow diagnostics — "why didn't this fire?" trace tool.

Step 19 of ``tasks/workflows/``. Surface lets operators pick a
contact + event_type and see, per subscribing workflow, exactly
which trigger condition rejected the enrolment (with the resolved
context paths) + whether the re-enrollment rule would block.

Read-only module — no transactions. Reads via DAL +
:mod:`core.events.conditions` for the AST shape.

The trigger-condition trace returned here is RICHER than the
production matcher's True/False — the matcher's hot path stays
performance-optimised (``evaluate_safe`` short-circuits on the
first False); the diagnostics trace evaluates every leaf so the
operator sees the full reasoning tree.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.models import Contact
from src.app.core.events.conditions import (
    InvalidCondition,
    SUPPORTED_OPS,
    _MISSING,
    _eval_leaf,
    _resolve_path,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


def _trace_evaluate(node: Any, context: Any) -> dict[str, Any]:
    """Recursive walker that returns a structured trace per AST
    node. Mirrors :func:`core.events.conditions.evaluate` but
    surfaces every leaf result + the resolved value instead of
    short-circuiting.

    Output schema:

    .. code-block:: json

        {"kind": "leaf",
         "op": "gte",
         "path": "lead.score",
         "value": 75,
         "resolved_value": 12,
         "missing": false,
         "result": false}

        {"kind": "all", "result": false,
         "children": [<trace>, ...]}
    """
    if node is None or node == {}:
        return {"kind": "empty", "result": True}
    if not isinstance(node, dict):
        return {
            "kind": "invalid",
            "result": False,
            "error": f"condition must be a dict (got {type(node).__name__})",
        }

    try:
        if "all" in node:
            children = node["all"]
            if not isinstance(children, list):
                raise InvalidCondition("'all' must be a list")
            child_traces = [_trace_evaluate(c, context) for c in children]
            return {
                "kind": "all",
                "result": all(t["result"] for t in child_traces),
                "children": child_traces,
            }
        if "any" in node:
            children = node["any"]
            if not isinstance(children, list):
                raise InvalidCondition("'any' must be a list")
            child_traces = [_trace_evaluate(c, context) for c in children]
            return {
                "kind": "any",
                "result": any(t["result"] for t in child_traces),
                "children": child_traces,
            }
        if "not" in node:
            child_trace = _trace_evaluate(node["not"], context)
            return {
                "kind": "not",
                "result": not child_trace["result"],
                "children": [child_trace],
            }

        # Leaf — resolve the path explicitly so the trace carries
        # both the literal value and the "was it missing" boolean.
        op = node.get("op")
        path = node.get("path")
        if not isinstance(op, str) or op not in SUPPORTED_OPS:
            raise InvalidCondition(f"unsupported op '{op}'")
        if not isinstance(path, str) or not path:
            raise InvalidCondition("leaf node missing 'path'")

        resolved = _resolve_path(context, path)
        missing = resolved is _MISSING
        result = _eval_leaf(node, context)
        return {
            "kind": "leaf",
            "op": op,
            "path": path,
            "value": node.get("value"),
            "resolved_value": None if missing else resolved,
            "missing": missing,
            "result": bool(result),
        }
    except InvalidCondition as exc:
        return {
            "kind": "invalid",
            "result": False,
            "error": str(exc),
        }


def synthesise_payload_for_event(
    *,
    contact: Contact,
    event_type: str,
) -> dict[str, Any]:
    """Build a plausible event-trigger payload from a contact row.

    The canonical publisher (see e.g.
    :func:`core.leads.service._publish_lead_created`) emits a dict
    with nested ``contact`` / ``lead`` / ``org`` sub-dicts. The
    diagnostics synthesiser mirrors that shape so trigger conditions
    that resolve ``contact.first_name`` / ``lead.score`` / etc.
    against the synthetic payload behave the same way they would
    against a real event.

    For event types we don't have a publisher rendering for yet,
    we attach only the ``contact`` sub-dict + top-level
    ``contact_id`` + ``event_type``. That covers the broad case
    (contact-attribute triggers) and degrades gracefully (lead /
    quote / invoice / order conditions resolve to missing, which
    the AST evaluator treats as fail-closed)."""

    contact_payload = {
        "id": str(contact.id),
        "full_name": contact.full_name,
        "first_name": (contact.full_name or "").split(" ", 1)[0] or None,
        "email": contact.email,
        "phone": contact.phone,
        "source": contact.source,
        "tags": list(contact.tags or []),
        "email_opt_out": bool(contact.email_opt_out),
    }
    # The custom_data JSONB is part of every contact-aware event so
    # conditions referencing custom fields evaluate correctly.
    if contact.custom_data:
        contact_payload["custom_data"] = dict(contact.custom_data)

    return {
        "event_type": event_type,
        "contact_id": str(contact.id),
        "contact": contact_payload,
        "synthesised": True,
    }


def _trigger_node_of(workflow: Workflow) -> dict[str, Any] | None:
    """Extract the trigger node from the workflow graph. Mirrors
    the matcher's lookup in :mod:`core.workflows.trigger_handlers`."""
    nodes = (workflow.graph or {}).get("nodes") or []
    return next(
        (n for n in nodes if str(n.get("type", "")).startswith("trigger")),
        None,
    )


async def _re_enrollment_decision(
    session: AsyncSession,
    *,
    workflow: Workflow,
    contact_id: uuid.UUID,
) -> str:
    """Decision string the diagnostics response carries: ``allowed``
    / ``blocked_once`` / ``blocked_daily``. Mirrors the live
    matcher's re-enrollment gate in :mod:`trigger_handlers`."""
    from src.app.core.workflows import data_access as _da

    rule = workflow.re_enrollment_rule
    if rule == WorkflowReEnrollmentRule.never:
        return "allowed"
    if rule == WorkflowReEnrollmentRule.once:
        existing = await _da.find_existing_run(
            session,
            workflow_id=workflow.id,
            contact_id=contact_id,
        )
        return "blocked_once" if existing is not None else "allowed"
    if rule == WorkflowReEnrollmentRule.daily:
        today_midnight = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        existing = await _da.find_existing_run(
            session,
            workflow_id=workflow.id,
            contact_id=contact_id,
            since_started_at=today_midnight,
        )
        return "blocked_daily" if existing is not None else "allowed"
    return "n/a"


async def _list_subscribing_workflows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
) -> list[Workflow]:
    """All workflows in the org whose ``enabled_event_types`` array
    contains ``event_type`` — INCLUDING drafts / paused. The matcher
    filters to ``active`` only; diagnostics shows the full set so
    the operator can see why a draft would or wouldn't fire if they
    activated it."""
    stmt = (
        select(Workflow)
        .where(Workflow.org_id == org_id)
        .where(Workflow.enabled_event_types.any(event_type))
        .order_by(Workflow.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def trace_event_for_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Top-level trace entry. Returns the diagnostics response
    payload for ``contact_id`` + ``event_type``.

    When ``payload`` is None, synthesises one from the contact's
    columns (mirrors what a publisher would emit). Otherwise the
    operator-supplied payload is used verbatim — useful for
    debugging a specific event the bus already received."""
    contact = (
        await session.execute(
            select(Contact).where(
                Contact.id == contact_id, Contact.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        return {
            "contact_id": contact_id,
            "event_type": event_type,
            "synthesised_payload": False,
            "entries": [],
        }

    synthesised = payload is None
    effective_payload = (
        synthesise_payload_for_event(contact=contact, event_type=event_type)
        if synthesised
        else dict(payload)
    )

    workflows = await _list_subscribing_workflows(
        session, org_id=org_id, event_type=event_type
    )

    entries: list[dict[str, Any]] = []
    for workflow in workflows:
        trigger_node = _trigger_node_of(workflow)
        if trigger_node is None:
            entries.append(
                {
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "eligible": False,
                    "reason": "workflow has no trigger node",
                    "trigger_condition_trace": None,
                    "re_enrollment_decision": "n/a",
                    "resolved_context": effective_payload,
                }
            )
            continue

        conditions = (trigger_node.get("config") or {}).get("conditions") or {}
        trace = _trace_evaluate(conditions, effective_payload)
        condition_pass = bool(trace["result"])

        re_enrollment = await _re_enrollment_decision(
            session, workflow=workflow, contact_id=contact_id
        )

        # Status is informational — the matcher filters to active,
        # but we show all so the operator can see "this draft
        # would match if activated".
        status_blocked = workflow.status != WorkflowStatus.active

        reason: str | None
        if status_blocked:
            reason = f"workflow status is {workflow.status.value} (matcher only fires on active)"
        elif not condition_pass:
            reason = "trigger condition rejected (see trace)"
        elif re_enrollment != "allowed":
            reason = f"re-enrollment rule blocked: {re_enrollment}"
        else:
            reason = None

        entries.append(
            {
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "eligible": (
                    not status_blocked
                    and condition_pass
                    and re_enrollment == "allowed"
                ),
                "reason": reason,
                "trigger_condition_trace": trace,
                "re_enrollment_decision": re_enrollment,
                "resolved_context": effective_payload,
            }
        )

    return {
        "contact_id": contact_id,
        "event_type": event_type,
        "synthesised_payload": synthesised,
        "entries": entries,
    }


__all__ = [
    "synthesise_payload_for_event",
    "trace_event_for_contact",
]
