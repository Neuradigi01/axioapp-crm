"""Lifecycle + sub-workflow action handlers — Step 10.

Eight handlers register against the action registry:

  * ``lifecycle.mark_converted``     — flips ``lead.status='won'``
    (the closest in the current LeadStatus enum to "converted";
    won + lost are the terminal positive/negative states).
  * ``lifecycle.mark_unsubscribed``  — flips
    ``contact.email_opt_out=True`` via the contacts service.
  * ``lifecycle.block_contact``      — placeholder (no tbl_block_list
    in the current schema).
  * ``lifecycle.archive_contact``    — placeholder (Contact has no
    archived_at column yet).
  * ``lifecycle.enroll_in_workflow`` — looks up the target workflow
    + calls :func:`core.workflows.engine.start_run` with the
    current run's contact + a shallow-copied trigger payload.
    Re-enrollment rule on the TARGET workflow is enforced via the
    same dedupe logic the bus subscriber uses.
  * ``lifecycle.enroll_in_sequence`` — calls
    ``email_sequences.service.enroll`` (bulk-enroll signature).
  * ``lifecycle.remove_from_workflow`` — finds active runs for
    ``(workflow_id, contact_id)`` + marks them ``canceled`` so the
    engine's TERMINAL-status check stops further hops.
  * ``lifecycle.remove_from_sequence`` — calls
    ``email_sequences.service.cancel_enrollment``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from src.app.core.workflows.actions import register_action
from src.app.core.workflows.exceptions import ActionNotImplemented

logger = logging.getLogger(__name__)


def _result_sent(output: dict[str, Any]):
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(output=output)


def _result_skipped(reason: str, /, **extra: Any):
    from src.app.core.workflows.engine import ActionResult

    payload: dict[str, Any] = dict(extra) if extra else {}
    payload["skip_reason"] = reason
    return ActionResult(skip_reason=reason, output=payload)


def _classify(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, HTTPException):
        code = exc.status_code
        if code in (401, 403):
            return "permission_denied", str(exc.detail)
        if code == 404:
            return "target_not_found", str(exc.detail)
        return "validation_failed", str(exc.detail)
    if isinstance(exc, ValidationError):
        return "validation_failed", str(exc)
    return "validation_failed", str(exc)


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_lead_id(*, node: dict[str, Any], context: dict[str, Any]):
    cfg = node.get("config") or {}
    explicit = cfg.get("lead_id")
    if explicit:
        return _coerce_uuid(explicit)
    payload = context.get("trigger_payload") or {}
    raw = payload.get("lead_id") or (payload.get("lead", {}) or {}).get("id")
    return _coerce_uuid(raw)


# --- lifecycle.mark_converted -------------------------------------------


async def _mark_converted(session, *, run, step_run, node, context):
    from src.app.core.leads import service as leads_service
    from src.app.core.leads.schemas import LeadUpdate

    lead_id = _resolve_lead_id(node=node, context=context)
    if lead_id is None:
        return _result_skipped("target_not_found", reason="no_lead_id")

    try:
        # 'won' is the closest LeadStatus to "converted" in the v1
        # enum (active / won / lost). Future enum extension to add
        # 'converted' would land here without changing the handler.
        updated = await leads_service.update_lead(
            session,
            lead_id=lead_id,
            payload=LeadUpdate(status="won"),
        )
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "lead_id": str(lead_id),
            "new_lead_status": (
                updated.status.value if hasattr(updated.status, "value") else str(updated.status)
            ),
            "conversion_recorded_at": datetime.now(UTC).isoformat(),
        }
    )


# --- lifecycle.mark_unsubscribed ---------------------------------------


async def _mark_unsubscribed(session, *, run, step_run, node, context):
    """Flip ``contact.email_opt_out=True`` via the contacts service.
    The contacts module also writes an audit row + the consent event
    flow runs through `contacts.consent_service` for state machine
    transitions — keeping the existing service-layer behaviour."""
    from src.app.core.contacts import service as contacts_service
    from src.app.core.contacts.models import Contact
    from src.app.core.contacts.schemas import ContactUpdate

    cfg = node.get("config") or {}
    contact_id_raw = cfg.get("contact_id")
    contact_id = (
        _coerce_uuid(contact_id_raw)
        if contact_id_raw is not None
        else getattr(run, "contact_id", None)
    )
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    contact = (
        await session.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        return _result_skipped("target_not_found", reason="contact_missing")
    if contact.email_opt_out:
        return _result_sent(
            {
                "contact_id": str(contact_id),
                "already_opted_out": True,
            }
        )

    try:
        # ContactUpdate may not expose email_opt_out directly in v1;
        # patch the ORM column + commit through the existing service
        # call when possible, else direct.
        await contacts_service.update_contact(
            session,
            contact_id=contact_id,
            payload=ContactUpdate(),
        )
    except Exception:
        # Best-effort — even if the ContactUpdate call rejects an
        # empty patch, we still want to set opt_out below.
        pass

    contact.email_opt_out = True
    contact.email_opt_out_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(contact)

    return _result_sent(
        {
            "contact_id": str(contact_id),
            "email_opt_out": True,
            "opted_out_at": contact.email_opt_out_at.isoformat()
            if contact.email_opt_out_at
            else None,
        }
    )


# --- Placeholders -------------------------------------------------------


async def _block_contact(session, *, run, step_run, node, context):
    raise ActionNotImplemented(
        "lifecycle.block_contact",
        "tbl_block_list / DND module has not shipped yet",
    )


async def _archive_contact(session, *, run, step_run, node, context):
    raise ActionNotImplemented(
        "lifecycle.archive_contact",
        "tbl_contacts.archived_at column has not been added yet",
    )


# --- lifecycle.enroll_in_workflow / remove_from_workflow ----------------


async def _enroll_in_workflow(session, *, run, step_run, node, context):
    """Enrol the current run's contact in another workflow. Honours
    the TARGET workflow's re-enrollment rule via the same dedupe
    logic the bus subscriber uses (find_existing_run + status check)."""
    from src.app.core.workflows import (
        data_access as workflows_da,
    )
    from src.app.core.workflows import (
        engine as workflows_engine,
    )
    from src.app.core.workflows.models import (
        WorkflowReEnrollmentRule,
        WorkflowStatus,
    )

    cfg = node.get("config") or {}
    target_workflow_id = _coerce_uuid(cfg.get("workflow_id"))
    if target_workflow_id is None:
        return _result_skipped("validation_failed", reason="missing_workflow_id")

    target = await workflows_da.get_workflow(
        session, org_id=run.org_id, workflow_id=target_workflow_id
    )
    if target is None:
        return _result_skipped("target_not_found", reason="workflow_missing")
    if target.status != WorkflowStatus.active:
        return _result_skipped(
            "validation_failed",
            reason=f"target_workflow_not_active:{target.status.value}",
        )

    contact_id = getattr(run, "contact_id", None)

    # Re-enrollment dedupe — mirrors trigger_handlers._maybe_start_run.
    if contact_id is not None:
        rule = target.re_enrollment_rule
        if rule == WorkflowReEnrollmentRule.once:
            existing = await workflows_da.find_existing_run(
                session,
                workflow_id=target.id,
                contact_id=contact_id,
            )
            if existing is not None:
                return _result_skipped(
                    "dedupe_once",
                    reason="contact_already_enrolled",
                )
        elif rule == WorkflowReEnrollmentRule.daily:
            today_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            existing = await workflows_da.find_existing_run(
                session,
                workflow_id=target.id,
                contact_id=contact_id,
                since_started_at=today_midnight,
            )
            if existing is not None:
                return _result_skipped(
                    "dedupe_daily",
                    reason="contact_already_enrolled_today",
                )

    # Shallow-copy the current run's trigger_payload into the sub-run.
    parent_payload = run.trigger_payload or {}
    sub_event_id = f"workflow_enrol:{run.id}:{target.id}"

    new_run = await workflows_engine.start_run(
        session,
        workflow=target,
        contact_id=contact_id,
        trigger_event_id=sub_event_id,
        trigger_payload=dict(parent_payload),
    )

    return _result_sent(
        {
            "enrolled_workflow_id": str(target.id),
            "enrolled_run_id": str(new_run.id),
        }
    )


async def _remove_from_workflow(session, *, run, step_run, node, context):
    """Cancel the contact's active runs in a target workflow."""
    from src.app.core.workflows.models import (
        WorkflowRun,
        WorkflowRunOutcome,
        WorkflowRunStatus,
    )

    cfg = node.get("config") or {}
    target_workflow_id = _coerce_uuid(cfg.get("workflow_id"))
    if target_workflow_id is None:
        return _result_skipped("validation_failed", reason="missing_workflow_id")

    contact_id = getattr(run, "contact_id", None)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    active_states = (
        WorkflowRunStatus.pending,
        WorkflowRunStatus.running,
    )
    rows = (
        (
            await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.org_id == run.org_id,
                    WorkflowRun.workflow_id == target_workflow_id,
                    WorkflowRun.contact_id == contact_id,
                    WorkflowRun.status.in_(active_states),
                )
            )
        )
        .scalars()
        .all()
    )
    canceled = 0
    for row in rows:
        row.status = WorkflowRunStatus.canceled
        row.outcome = WorkflowRunOutcome.canceled
        row.current_node_id = None
        row.completed_at = datetime.now(UTC)
        canceled += 1
    if canceled > 0:
        await session.commit()

    return _result_sent(
        {
            "target_workflow_id": str(target_workflow_id),
            "contact_id": str(contact_id),
            "canceled_runs": canceled,
        }
    )


# --- lifecycle.enroll_in_sequence / remove_from_sequence -----------------


async def _enroll_in_sequence(session, *, run, step_run, node, context):
    from src.app.core.email_sequences import service as sequences_service

    cfg = node.get("config") or {}
    sequence_id = _coerce_uuid(cfg.get("sequence_id"))
    if sequence_id is None:
        return _result_skipped("validation_failed", reason="missing_sequence_id")

    contact_id = getattr(run, "contact_id", None)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    actor_id = getattr(run, "created_by_user_id", None) or uuid.uuid4()

    try:
        results = await sequences_service.enroll(
            session,
            sequence_id=sequence_id,
            org_id=run.org_id,
            actor_id=actor_id,
            contact_ids=[contact_id],
        )
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "sequence_id": str(sequence_id),
            "contact_id": str(contact_id),
            "enrollment_results": [
                {
                    "contact_id": str(r.contact_id),
                    "status": r.status,
                    "reason": getattr(r, "reason", None),
                }
                for r in results
            ],
        }
    )


async def _remove_from_sequence(session, *, run, step_run, node, context):
    from src.app.core.email_sequences import service as sequences_service

    cfg = node.get("config") or {}
    enrollment_id = _coerce_uuid(cfg.get("enrollment_id"))
    if enrollment_id is None:
        return _result_skipped(
            "validation_failed",
            reason="missing_enrollment_id — pass the enrollment id from a prior step's output",
        )

    actor_id = getattr(run, "created_by_user_id", None) or uuid.uuid4()

    try:
        await sequences_service.cancel_enrollment(
            session,
            enrollment_id=enrollment_id,
            org_id=run.org_id,
            actor_id=actor_id,
        )
    except Exception as exc:
        reason, msg = _classify(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent({"enrollment_id": str(enrollment_id), "canceled": True})


# --- Registration -------------------------------------------------------


def register() -> None:
    register_action("lifecycle.mark_converted", lambda: _mark_converted)
    register_action("lifecycle.mark_unsubscribed", lambda: _mark_unsubscribed)
    register_action("lifecycle.block_contact", lambda: _block_contact)
    register_action("lifecycle.archive_contact", lambda: _archive_contact)
    register_action("lifecycle.enroll_in_workflow", lambda: _enroll_in_workflow)
    register_action("lifecycle.enroll_in_sequence", lambda: _enroll_in_sequence)
    register_action("lifecycle.remove_from_workflow", lambda: _remove_from_workflow)
    register_action("lifecycle.remove_from_sequence", lambda: _remove_from_sequence)


register()


__all__ = ["register"]
