"""Record-mutation action handlers for the workflows engine — Step 8.

Eight production handlers + one placeholder (the order module hasn't
shipped yet):

  * ``record.update_contact_field`` — patches a Contact via
    ``contacts.service.update_contact``.
  * ``record.update_lead_field``    — patches a Lead via
    ``leads.service.update_lead``.
  * ``record.update_lead_stage``    — convenience wrapper that mutates
    ``pipeline_stage`` + lets the downstream
    ``lead.status_changed`` publisher fire.
  * ``record.create_task``          — creates a Task via
    ``tasks.service.create_task``. Title + description support
    ``{{ contact.full_name }}`` style variable interpolation.
  * ``record.create_note``          — adds a timeline note via
    ``activities.service.log``.
  * ``record.create_appointment``   — schedules an appointment via
    ``appointments.service.create_appointment``.
  * ``record.create_quote``         — registered as a placeholder;
    raises :class:`ActionNotImplemented` until ``core/quotes/`` ships.
  * ``record.create_invoice``       — creates a draft invoice via
    ``billing.service.create_draft``.
  * ``record.create_order``         — registered as a placeholder;
    raises :class:`ActionNotImplemented` until ``core/orders/`` ships.

Cross-module discipline (per CLAUDE.md): every handler imports the
origin module's ``service.py`` — NEVER its ``data_access.py`` — so
the origin module's permission checks, custom-field validation,
audit emits, and downstream event publishers fire correctly.

The ``ActionResult.output`` of each handler carries the
new/updated record's id + the touched fields so downstream nodes
can branch on them via the engine's per-step output map.

Error policy: origin-service exceptions are caught + mapped to
``skip_reason`` shapes:

  * ``EntityNotFound`` / 404-shaped exceptions → ``target_not_found``
  * ``ValidationError`` / Pydantic ValidationError → ``validation_failed``
  * Permission denials (currently mostly 403 from the router layer
    — services raise these too if they enforce ownership) →
    ``permission_denied``

The :class:`ActionNotImplemented` exception is intentionally NOT
caught here — the engine's outer except-handler maps it to
``run.status='errored'`` so the operator sees it on the
run-history view as a hard failure rather than a quiet skip.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from src.app.core.workflows.actions import register_action
from src.app.core.workflows.exceptions import ActionNotImplemented

logger = logging.getLogger(__name__)


# --- Helpers -------------------------------------------------------------


def _result_sent(output: dict[str, Any]):
    """Standard success ActionResult shape — no edge label, no skip."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult(output=output)


def _result_skipped(reason: str, /, **extra: Any):
    from src.app.core.workflows.engine import ActionResult

    payload: dict[str, Any] = dict(extra) if extra else {}
    payload["skip_reason"] = reason
    return ActionResult(skip_reason=reason, output=payload)


def _render(value: Any, context: dict[str, Any]) -> Any:
    """Lenient template render against the context. Non-string
    values pass through unchanged so a node config like
    ``{"due_in_days": 7}`` doesn't get stringified."""
    if not isinstance(value, str):
        return value
    from src.app.core.templates.variables import resolve as render_resolve

    return render_resolve(value, context)


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_target_contact_id(
    *, run, node: dict[str, Any], context: dict[str, Any]
) -> uuid.UUID | None:
    """Honour ``config.contact_id_source`` per the spec.

    Valid sources:
      * ``"run.contact_id"`` (default) — the run row's contact.
      * ``"trigger_payload.<dot-path>"`` — walk the trigger payload.

    Returns None when the source doesn't resolve."""
    cfg = node.get("config") or {}
    source = cfg.get("contact_id_source") or "run.contact_id"
    if source == "run.contact_id":
        return getattr(run, "contact_id", None)
    if isinstance(source, str) and source.startswith("trigger_payload."):
        path = source.split(".", 1)[1]
        cursor: Any = context.get("trigger_payload") or {}
        for segment in path.split("."):
            if not isinstance(cursor, dict) or segment not in cursor:
                return None
            cursor = cursor[segment]
        return _coerce_uuid(cursor)
    return None


def _resolve_target_lead_id(*, node: dict[str, Any], context: dict[str, Any]) -> uuid.UUID | None:
    """The trigger payload's ``lead_id`` or ``lead.id`` is the
    default target. Operators can override via ``config.lead_id``
    (typically resolved via a prior step's output)."""
    cfg = node.get("config") or {}
    explicit = cfg.get("lead_id")
    if explicit:
        return _coerce_uuid(explicit)

    payload = context.get("trigger_payload") or {}
    direct = payload.get("lead_id")
    if direct:
        return _coerce_uuid(direct)
    lead = payload.get("lead")
    if isinstance(lead, dict):
        return _coerce_uuid(lead.get("id"))
    return None


def _apply_field_path(target: dict[str, Any], path: str, value: Any) -> None:
    """Mutate ``target`` so ``target[<path>]`` becomes ``value``.

    Supports the dot-prefixed ``custom_data.<key>`` shorthand by
    splitting on the first dot — anything before becomes a top-level
    column name on the target payload, anything after becomes a key
    inside the custom_data dict.
    """
    if path.startswith("custom_data."):
        key = path[len("custom_data.") :]
        cd = dict(target.get("custom_data") or {})
        cd[key] = value
        target["custom_data"] = cd
        return
    target[path] = value


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an origin-service exception to a (skip_reason, error_msg)
    pair. Falls through to ``("validation_failed", str(exc))`` for
    anything not pattern-matched so the run-history view still
    surfaces the message."""
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        if status_code in (401, 403):
            return "permission_denied", str(exc.detail)
        if status_code == 404:
            return "target_not_found", str(exc.detail)
        if status_code in (400, 409, 422):
            return "validation_failed", str(exc.detail)
        return "validation_failed", str(exc.detail)
    if isinstance(exc, ValidationError):
        return "validation_failed", str(exc)
    if isinstance(exc, PermissionError):
        return "permission_denied", str(exc)
    if isinstance(exc, LookupError):
        return "target_not_found", str(exc)
    if isinstance(exc, ValueError):
        return "validation_failed", str(exc)
    return "validation_failed", str(exc)


# --- Update handlers -----------------------------------------------------


async def _update_contact_field(session, *, run, step_run, node, context):
    from src.app.core.contacts import service as contacts_service
    from src.app.core.contacts.schemas import ContactUpdate

    cfg = node.get("config") or {}
    contact_id = _resolve_target_contact_id(run=run, node=node, context=context)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    field_path = cfg.get("field_path")
    if not isinstance(field_path, str) or not field_path:
        return _result_skipped("validation_failed", reason="missing_field_path")

    new_value = _render(cfg.get("value"), context)
    update_payload: dict[str, Any] = {}
    _apply_field_path(update_payload, field_path, new_value)

    try:
        patch = ContactUpdate(**update_payload)
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    try:
        updated = await contacts_service.update_contact(
            session, contact_id=contact_id, payload=patch
        )
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "contact_id": str(updated.id),
            "updated_field": field_path,
            "updated_value": new_value,
        }
    )


async def _update_lead_field(session, *, run, step_run, node, context):
    from src.app.core.leads import service as leads_service
    from src.app.core.leads.schemas import LeadUpdate

    cfg = node.get("config") or {}
    lead_id = _resolve_target_lead_id(node=node, context=context)
    if lead_id is None:
        return _result_skipped("target_not_found", reason="no_lead_id")

    field_path = cfg.get("field_path")
    if not isinstance(field_path, str) or not field_path:
        return _result_skipped("validation_failed", reason="missing_field_path")

    new_value = _render(cfg.get("value"), context)
    update_payload: dict[str, Any] = {}
    _apply_field_path(update_payload, field_path, new_value)

    try:
        patch = LeadUpdate(**update_payload)
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    try:
        updated = await leads_service.update_lead(session, lead_id=lead_id, payload=patch)
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "lead_id": str(updated.id),
            "updated_field": field_path,
            "updated_value": new_value,
        }
    )


async def _update_lead_stage(session, *, run, step_run, node, context):
    """Convenience wrapper — mutates ``pipeline_stage`` so a single
    operator-friendly node sets the pipeline + lets the leads
    service's downstream stage-changed publisher fire."""
    from src.app.core.leads import service as leads_service
    from src.app.core.leads.schemas import LeadUpdate

    cfg = node.get("config") or {}
    lead_id = _resolve_target_lead_id(node=node, context=context)
    if lead_id is None:
        return _result_skipped("target_not_found", reason="no_lead_id")

    new_stage = _render(cfg.get("pipeline_stage"), context)
    if not isinstance(new_stage, str) or not new_stage.strip():
        return _result_skipped("validation_failed", reason="missing_pipeline_stage")

    try:
        patch = LeadUpdate(pipeline_stage=new_stage.strip())
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    try:
        updated = await leads_service.update_lead(session, lead_id=lead_id, payload=patch)
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "lead_id": str(updated.id),
            "pipeline_stage": new_stage,
        }
    )


# --- Create handlers -----------------------------------------------------


async def _create_task(session, *, run, step_run, node, context):
    from src.app.core.tasks import service as tasks_service
    from src.app.core.tasks.schemas import TaskCreate

    cfg = node.get("config") or {}
    title = _render(cfg.get("title"), context)
    if not isinstance(title, str) or not title.strip():
        return _result_skipped("validation_failed", reason="missing_title")

    description = _render(cfg.get("description"), context)
    due_in_days = cfg.get("due_in_days")
    due_at: datetime | None = None
    if isinstance(due_in_days, (int, float)) and due_in_days > 0:
        due_at = datetime.now(UTC) + timedelta(days=int(due_in_days))

    priority = cfg.get("priority", "med")
    related_to = cfg.get("related_to")
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    if related_to in ("contact", "lead", "appointment", "quote", "invoice"):
        related_entity_type = related_to
        if related_to == "contact":
            related_entity_id = getattr(run, "contact_id", None)
        elif related_to == "lead":
            related_entity_id = _resolve_target_lead_id(node=node, context=context)

    assignee_id = _coerce_uuid(cfg.get("assignee_user_id"))

    actor_user_id = (
        getattr(run, "created_by_user_id", None)
        or assignee_id
        or uuid.uuid4()  # System-author fallback; tasks service requires non-null.
    )

    try:
        payload = TaskCreate(
            title=title,
            description=description if isinstance(description, str) else None,
            due_at=due_at,
            assigned_to_id=assignee_id,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            priority=priority,
        )
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    try:
        task = await tasks_service.create_task(
            session,
            org_id=run.org_id,
            current_user_id=actor_user_id,
            payload=payload,
        )
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "task_id": str(task.id),
            "task_title": task.title,
            "task_due_at": (task.due_at.isoformat() if task.due_at else None),
            "task_assignee_id": (str(task.assigned_to_id) if task.assigned_to_id else None),
        }
    )


async def _create_note(session, *, run, step_run, node, context):
    """Adds a free-text note to the contact's activity timeline.
    Uses ``activities.service.log`` which already handles tenant
    context + audit emits."""
    from src.app.core import activities
    from src.app.core.activities.models import ActivityType

    cfg = node.get("config") or {}
    contact_id = _resolve_target_contact_id(run=run, node=node, context=context)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    body = _render(cfg.get("body"), context)
    if not isinstance(body, str) or not body.strip():
        return _result_skipped("validation_failed", reason="missing_body")

    try:
        await activities.log(
            entity_type="contact",
            entity_id=contact_id,
            type=ActivityType.note,
            payload={"text": body.strip()},
            org_id=run.org_id,
        )
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent({"contact_id": str(contact_id), "note_body": body.strip()})


async def _create_appointment(session, *, run, step_run, node, context):
    from src.app.core.appointments import service as appointments_service
    from src.app.core.appointments.schemas import AppointmentCreate

    cfg = node.get("config") or {}
    contact_id = _resolve_target_contact_id(run=run, node=node, context=context)
    if contact_id is None:
        return _result_skipped("target_not_found", reason="no_contact_id")

    title = _render(cfg.get("title"), context)
    if not isinstance(title, str) or not title.strip():
        return _result_skipped("validation_failed", reason="missing_title")

    delay_days = cfg.get("delay_days", 1)
    scheduled_at = datetime.now(UTC) + timedelta(
        days=int(delay_days) if isinstance(delay_days, (int, float)) else 1
    )

    duration_min = cfg.get("duration_min", 30)
    assigned_to_id = _coerce_uuid(cfg.get("assigned_to_id"))
    if assigned_to_id is None:
        return _result_skipped("validation_failed", reason="missing_assigned_to_id")

    location = _render(cfg.get("location"), context)
    purpose = _render(cfg.get("purpose"), context)

    try:
        payload = AppointmentCreate(
            contact_id=contact_id,
            title=title.strip(),
            purpose=purpose if isinstance(purpose, str) else None,
            scheduled_at=scheduled_at,
            duration_min=int(duration_min),
            location=location if isinstance(location, str) else None,
            assigned_to_id=assigned_to_id,
        )
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    actor_user_id = getattr(run, "created_by_user_id", None) or assigned_to_id

    try:
        appt = await appointments_service.create_appointment(
            session,
            org_id=run.org_id,
            current_user_id=actor_user_id,
            payload=payload,
        )
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    return _result_sent(
        {
            "appointment_id": str(appt.id),
            "appointment_scheduled_at": appt.scheduled_at.isoformat(),
        }
    )


async def _create_invoice(session, *, run, step_run, node, context):
    """Drafts a new invoice via ``billing.service.create_draft``.
    The operator pre-configures line items in node config —
    iterated + added via ``billing.service.add_line``."""
    from src.app.core.billing import service as billing_service
    from src.app.core.billing.schemas import InvoiceCreate, InvoiceLineCreate

    cfg = node.get("config") or {}
    contact_id = _resolve_target_contact_id(run=run, node=node, context=context)

    actor_user_id = getattr(run, "created_by_user_id", None) or uuid.uuid4()

    try:
        invoice_payload = InvoiceCreate(
            contact_id=contact_id,
            notes=(
                _render(cfg.get("notes"), context) if isinstance(cfg.get("notes"), str) else None
            ),
            currency=cfg.get("currency", "INR"),
        )
    except ValidationError as exc:
        return _result_skipped("validation_failed", error=str(exc))

    try:
        invoice = await billing_service.create_draft(
            session,
            org_id=run.org_id,
            user_id=actor_user_id,
            payload=invoice_payload,
        )
    except Exception as exc:
        reason, msg = _classify_exception(exc)
        return _result_skipped(reason, error=msg)

    items = cfg.get("items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            line_payload = InvoiceLineCreate(
                description=_render(item.get("description", ""), context),
                quantity=item.get("quantity", 1),
                unit_price=item.get("unit_price", 0),
                tax_rate=item.get("tax_rate", 0),
            )
            await billing_service.add_line(
                session,
                invoice_id=invoice.id,
                user_id=actor_user_id,
                payload=line_payload,
            )
        except Exception as exc:
            logger.warning("workflows.records.create_invoice add_line failed: %s", exc)
            # Continue with remaining items + the draft invoice;
            # don't kill the whole step for one bad line.

    return _result_sent(
        {
            "invoice_id": str(invoice.id),
            "invoice_currency": invoice.currency,
        }
    )


async def _create_quote(session, *, run, step_run, node, context):
    """Placeholder — the quotes module hasn't shipped yet. Raises
    :class:`ActionNotImplemented` so the run lands as errored with
    a clear reason."""
    raise ActionNotImplemented(
        "record.create_quote",
        "core/quotes/ has not shipped yet",
    )


async def _create_order(session, *, run, step_run, node, context):
    """Placeholder — the orders module hasn't shipped yet."""
    raise ActionNotImplemented(
        "record.create_order",
        "core/orders/ has not shipped yet",
    )


# --- Registration -------------------------------------------------------


def register() -> None:
    """Register the 9 record handlers. Idempotent."""
    register_action("record.update_contact_field", lambda: _update_contact_field)
    register_action("record.update_lead_field", lambda: _update_lead_field)
    register_action("record.update_lead_stage", lambda: _update_lead_stage)
    register_action("record.create_task", lambda: _create_task)
    register_action("record.create_note", lambda: _create_note)
    register_action("record.create_appointment", lambda: _create_appointment)
    register_action("record.create_quote", lambda: _create_quote)
    register_action("record.create_invoice", lambda: _create_invoice)
    register_action("record.create_order", lambda: _create_order)


# Side-effect registration on import.
register()


__all__ = ["register"]
