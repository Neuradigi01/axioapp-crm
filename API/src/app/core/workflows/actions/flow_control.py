"""Flow-control action handlers — ``branch.if`` + ``branch.switch``.

Branch handler (:func:`_branch_handler`) walks the node's
``config.branches`` list in order, evaluates each branch's
``conditions`` against the engine's context, and returns the first
matching ``label`` as the :class:`ActionResult.next_edge_label`.
When no branch matches, returns ``"else"`` — every branch node
MUST have an outbound edge with ``label='else'`` (Step 2's graph
validator enforces this).

Switch handler (:func:`_switch_handler`) reads a single value at
``config.path``, then walks ``config.branches`` matching by
equality on ``branch.value``. When nothing matches, returns
``"default"`` — every switch node MUST have an outbound edge with
``label='default'``.

Both handlers are I/O-free — they read from the engine's
``context`` dict (the same shape Step 4 builds: ``contact`` /
``trigger_payload`` / ``run_state``). The Step-2 graph validator
will reject any branch / switch node that doesn't carry the
required ``else`` / ``default`` outbound edge so the operator
gets a clear 422 at publish time instead of a runtime miss.

The remaining flow nodes (``flow.wait``, ``flow.wait_for_event``,
``flow.end``, ``flow.goal``, ``flow.ab_split``) ship in Step 11.
Step 6 only registers the two branch handlers because they're the
minimum needed to validate the condition AST end-to-end.
"""

from __future__ import annotations

import logging
from typing import Any

from src.app.core.events.conditions import evaluate_safe
from src.app.core.workflows.actions import register_action

logger = logging.getLogger(__name__)


_BRANCH_DEFAULT_LABEL = "else"
_SWITCH_DEFAULT_LABEL = "default"


async def _branch_handler(
    session,
    *,
    run,
    step_run,
    node: dict[str, Any],
    context: dict[str, Any],
):
    """Walk ``config.branches`` in order; return the first matching
    label. Empty branches list → ``"else"`` immediately."""
    from src.app.core.workflows.engine import ActionResult

    branches = (node.get("config") or {}).get("branches") or []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        label = branch.get("label")
        conditions = branch.get("conditions") or {}
        if not isinstance(label, str) or not label:
            continue
        if evaluate_safe(conditions, context):
            return ActionResult(next_edge_label=label)

    return ActionResult(next_edge_label=_BRANCH_DEFAULT_LABEL)


async def _switch_handler(
    session,
    *,
    run,
    step_run,
    node: dict[str, Any],
    context: dict[str, Any],
):
    """Read one value off the context + match by equality against
    every ``branches[].value``. Missing path / no match falls
    through to ``"default"``."""
    from src.app.core.events.conditions import _MISSING, _resolve_path
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    path = cfg.get("path")
    branches = cfg.get("branches") or []

    if not isinstance(path, str) or not path:
        return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)

    resolved = _resolve_path(context, path)
    if resolved is _MISSING:
        return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        label = branch.get("label")
        target = branch.get("value")
        if isinstance(label, str) and label and resolved == target:
            return ActionResult(next_edge_label=label)

    return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)


# --- Step-11 handlers ----------------------------------------------------


import hashlib  # noqa: E402
import logging  # noqa: E402
import uuid as _uuid_mod  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

_logger = logging.getLogger(__name__)


# Cap from the graph validator: wait nodes must have
# max_wait_seconds ≤ 30 days.
_MAX_WAIT_SECONDS = 30 * 24 * 60 * 60


async def _wait_handler(session, *, run, step_run, node, context):
    """No-op pass-through. The engine's ``_advance`` recognises the
    wait node by type AFTER the handler returns + parks the run by
    setting ``next_step_at = now + delay_seconds``. Step-4 ships
    the parking logic; Step-11 just registers the explicit
    ``flow_control.wait`` action type so the validator + the
    action-registry agree the type is valid."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult()


async def _ab_split_handler(session, *, run, step_run, node, context):
    """Deterministic 50/50 (or weighted) random branch. The split is
    seeded by ``(run.id, node.id)`` so re-running the same node on
    the same run picks the same edge — useful for diagnostics
    reproducibility + makes the A/B-test cohort assignment stable
    across Celery retries."""
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    weights_raw = cfg.get("weights")
    # Default 50/50 — two-element list [a_weight, b_weight].
    weights = (
        [int(w) for w in weights_raw]
        if isinstance(weights_raw, (list, tuple)) and len(weights_raw) == 2
        else [50, 50]
    )
    total = max(1, weights[0] + weights[1])

    seed_material = f"{getattr(run, 'id', '')}:{node.get('id', '')}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
    # First 8 bytes → integer → modulo total. Deterministic +
    # uniformly distributed.
    bucket = int.from_bytes(digest[:8], "big") % total
    label = "a" if bucket < weights[0] else "b"
    return ActionResult(
        next_edge_label=label,
        output={"weights": weights, "bucket": bucket, "label": label},
    )


async def _goal_handler(session, *, run, step_run, node, context):
    """Marker action — returns ``next_edge_label=None`` so the
    engine's ``_advance`` treats the node as terminal. The engine
    checks ``workflow.goal_node_id == executed_node_id`` + sets
    ``run.outcome = goal_reached`` automatically.

    Operators add this node anywhere they want "the funnel made
    it" tracking — Step 19's analytics view will count goal
    completions for conversion-rate math.
    """
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(output={"goal_marker": True})


async def _wait_for_event_handler(session, *, run, step_run, node, context):
    """Park the run + register a wait row in
    ``tbl_workflow_event_waits``. The Step-5 trigger handler
    resumes the run on a matching event; the Step-11 beat sweep
    resumes on timeout.

    Node config:
      * ``event_type``       — the event-type string to wait for.
      * ``max_wait_seconds`` — capped at 30 days by the validator.
      * ``contact_match``    — when True (default), only events
        published for the run's contact_id resume; when False, ANY
        event of the type resumes (org-wide events).
    """
    from src.app.core.workflows import data_access as _wf_da
    from src.app.core.workflows.engine import ActionResult
    from src.app.core.workflows.models import (
        WorkflowEventWait,
        WorkflowRunStatus,
    )

    cfg = node.get("config") or {}
    event_type = cfg.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "missing_event_type"},
        )

    max_wait = cfg.get("max_wait_seconds", 24 * 60 * 60)
    if not isinstance(max_wait, (int, float)) or max_wait <= 0:
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "invalid_max_wait_seconds"},
        )
    max_wait = min(int(max_wait), _MAX_WAIT_SECONDS)

    contact_match = bool(cfg.get("contact_match", True))
    wait_contact_id = getattr(run, "contact_id", None) if contact_match else None

    expires_at = datetime.now(UTC) + timedelta(seconds=max_wait)

    wait = WorkflowEventWait(
        org_id=run.org_id,
        run_id=run.id,
        node_id=node.get("id"),
        event_type=event_type,
        contact_id=wait_contact_id,
        expires_at=expires_at,
    )
    _wf_da.insert_event_wait(session, wait)

    # Park the run — the engine's normal _advance path would
    # follow an outbound edge, but here we want to pause until
    # something external resumes us. Set next_step_at to the
    # timeout so the beat sweep + the engine's existing pending
    # sweep both see this row.
    run.status = WorkflowRunStatus.pending
    run.next_step_at = expires_at
    await session.commit()

    # The engine's _advance will see status='pending' on a wait-type
    # node + skip the re-enqueue. We return a noop ActionResult; the
    # engine's caller path checks the node's type and parks
    # accordingly. The output carries the wait_id so the run-history
    # drawer can show "waiting on event_type X until …".
    return ActionResult(
        output={
            "wait_id": str(wait.id),
            "event_type": event_type,
            "expires_at": expires_at.isoformat(),
            "contact_match": contact_match,
        }
    )


async def _call_webhook_handler(session, *, run, step_run, node, context):
    """POST a rendered body to an external URL. Per-config behaviour
    on failure: ``on_failure='skip'`` (default) yields a
    ``skip_reason='webhook_failed'``; ``on_failure='error'`` raises
    so the engine's outer except marks the run errored.

    Config keys:
      * ``url``                — https-only target.
      * ``method``             — defaults to ``POST`` (only POST
                                supported in v1).
      * ``body_template``      — string passed through
                                ``templates.variables.resolve``.
      * ``headers``            — dict of static request headers.
      * ``expected_status_codes`` — list of integer statuses
                                considered success (defaults to
                                ``[200, 201, 202, 204]``).
      * ``on_failure``         — ``"skip"`` (default) or ``"error"``.
    """
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    url = cfg.get("url")
    method = (cfg.get("method") or "POST").upper()
    expected = cfg.get("expected_status_codes") or [200, 201, 202, 204]
    on_failure = cfg.get("on_failure", "skip")
    body_template = cfg.get("body_template") or ""
    headers = cfg.get("headers") or {}

    if not isinstance(url, str) or not url.startswith("https://"):
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "invalid_webhook_url"},
        )
    if method != "POST":
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "only_POST_supported"},
        )

    # Render the body against the engine context.
    from src.app.core.templates.variables import resolve as render_resolve

    rendered_body = (
        render_resolve(body_template, context)
        if isinstance(body_template, str)
        else str(body_template)
    )

    try:
        import httpx
    except ImportError:  # pragma: no cover — pinned dep in prod
        return ActionResult(
            skip_reason="channel_error",
            output={"skip_reason": "httpx_not_installed"},
        )

    request_headers = dict(headers)
    request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("X-Idempotency-Key", str(getattr(step_run, "id", "")) or "")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, content=rendered_body, headers=request_headers)
    except Exception as exc:
        if on_failure == "error":
            raise
        return ActionResult(
            skip_reason="webhook_failed",
            output={"skip_reason": "request_error", "error": str(exc)},
        )

    if response.status_code not in expected:
        if on_failure == "error":
            raise RuntimeError(f"webhook returned {response.status_code}: {response.text[:200]}")
        return ActionResult(
            skip_reason="webhook_failed",
            output={
                "skip_reason": f"unexpected_status:{response.status_code}",
                "response_body": response.text[:500],
            },
        )

    return ActionResult(
        output={
            "webhook_status": response.status_code,
            "response_snippet": response.text[:200],
        }
    )


async def _notify_user_handler(session, *, run, step_run, node, context):
    """Send an in-app notification via ``core.notifications.service``.
    Recipient resolver options:
      * ``"workflow_owner"`` — the workflow's ``created_by_user_id``.
      * ``"lead_owner"``     — pulls ``lead.assigned_to_id`` from the
                              trigger payload (lead.<id> snapshot).
      * ``"specific_user"``  — node config supplies ``user_id``.
    """
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    recipient_kind = cfg.get("recipient", "workflow_owner")
    title_template = cfg.get("title") or "Workflow notification"
    body_template = cfg.get("body") or ""
    notif_type = cfg.get("type", "workflow.notify_user")

    target_user_id: _uuid_mod.UUID | None = None
    if recipient_kind == "workflow_owner":
        target_user_id = getattr(run, "created_by_user_id", None)
        if target_user_id is None:
            # Fall back to the workflow row's creator via DB.
            from src.app.core.workflows import data_access as _wf_da

            workflow = await _wf_da.get_workflow(
                session, org_id=run.org_id, workflow_id=run.workflow_id
            )
            if workflow is not None:
                target_user_id = workflow.created_by_user_id
    elif recipient_kind == "lead_owner":
        payload = context.get("trigger_payload") or {}
        lead = payload.get("lead") or {}
        raw = lead.get("assigned_to_id") if isinstance(lead, dict) else None
        try:
            target_user_id = _uuid_mod.UUID(str(raw)) if raw else None
        except (ValueError, TypeError):
            target_user_id = None
    elif recipient_kind == "specific_user":
        raw = cfg.get("user_id")
        try:
            target_user_id = _uuid_mod.UUID(str(raw)) if raw else None
        except (ValueError, TypeError):
            target_user_id = None

    if target_user_id is None:
        return ActionResult(
            skip_reason="target_not_found",
            output={"skip_reason": "no_recipient"},
        )

    from src.app.core.templates.variables import resolve as render_resolve

    title = render_resolve(title_template, context)
    body = render_resolve(body_template, context) if body_template else None

    try:
        from src.app.core.notifications import service as notifications_service

        await notifications_service.notify(
            org_id=run.org_id,
            user_id=target_user_id,
            type=notif_type,
            title=title or "Workflow notification",
            body=body,
            payload={"run_id": str(run.id), "node_id": node.get("id")},
        )
    except Exception as exc:
        _logger.warning(
            "workflows.flow_control.notify_user failed run=%s error=%s",
            run.id,
            exc,
        )
        return ActionResult(
            skip_reason="channel_error",
            output={"skip_reason": "notify_failed", "error": str(exc)},
        )

    return ActionResult(output={"notified_user_id": str(target_user_id), "title": title})


async def _log_internal_note_handler(session, *, run, step_run, node, context):
    """Internal-only timeline note — same path as ``record.create_note``
    but with ``is_internal=True`` flagged in the payload so the
    contact-detail timeline can hide it from "shared with customer"
    views. Defers to ``activities.service.log`` (which carries the
    flag through via ``payload``)."""
    from src.app.core.activities.models import ActivityType
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    contact_id = getattr(run, "contact_id", None)
    if contact_id is None:
        return ActionResult(
            skip_reason="target_not_found",
            output={"skip_reason": "no_contact_id"},
        )

    from src.app.core.templates.variables import resolve as render_resolve

    body = render_resolve(cfg.get("body") or "", context)
    if not isinstance(body, str) or not body.strip():
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "missing_body"},
        )

    try:
        from src.app.core import activities

        await activities.log(
            entity_type="contact",
            entity_id=contact_id,
            type=ActivityType.note,
            payload={"text": body.strip(), "is_internal": True},
            org_id=run.org_id,
        )
    except Exception as exc:
        return ActionResult(
            skip_reason="validation_failed",
            output={"skip_reason": "activity_log_failed", "error": str(exc)},
        )

    return ActionResult(output={"contact_id": str(contact_id), "is_internal": True})


def register() -> None:
    """Register the two Step-6 branch handlers + the seven Step-11
    flow-control handlers. Imported at workflows package init so
    the registry knows about them before any engine dispatch."""
    # Step 6 — branch + switch.
    register_action("branch.if", lambda: _branch_handler)
    register_action("branch.switch", lambda: _switch_handler)
    # Step 11 — wait / a-b / goal / wait-for-event / webhook /
    # notify / internal-note.
    register_action("flow_control.wait", lambda: _wait_handler)
    register_action("flow_control.ab_split", lambda: _ab_split_handler)
    register_action("flow_control.goal", lambda: _goal_handler)
    register_action("flow_control.wait_for_event", lambda: _wait_for_event_handler)
    register_action("flow_control.call_webhook", lambda: _call_webhook_handler)
    register_action("flow_control.notify_user", lambda: _notify_user_handler)
    register_action("flow_control.log_internal_note", lambda: _log_internal_note_handler)


# Side-effect registration on import so the engine resolves
# branch.* / flow_control.* nodes without any extra wiring.
register()


__all__ = ["register"]
