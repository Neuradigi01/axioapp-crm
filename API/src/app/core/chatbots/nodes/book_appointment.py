"""Book Appointment node (``tasks/chatbot-builder`` Step 10).

Creates an appointment via :func:`core.appointments.service.create_appointment`.
The conflict-check inside that service already raises HTTPException
409; we catch it and route to the ``busy`` port.

Config shape::

    {
      "title_template": "Bot appointment for {{contact.full_name}}",
      "duration_minutes": 30,
      "scheduled_at_from": "answers.slot",   # ISO-8601 string from an Ask node
      "assigned_to_user_id": "<uuid>",       # required
      "location": "Zoom",                    # optional
      "purpose": null                        # optional
    }

Output ports: ``booked`` (default), ``busy`` (conflict), ``error``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "book_appointment"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    title_template = str(cfg.get("title_template") or "Bot appointment")
    duration_minutes = int(cfg.get("duration_minutes") or 30)
    scheduled_at_path = str(cfg.get("scheduled_at_from") or "")
    assignee_raw = cfg.get("assigned_to_user_id")

    if ctx.run.contact_id is None:
        return NodeResult(
            skip_reason="no_contact_on_run",
            output={"reason": "book_appointment needs a contact_id"},
        )
    if not assignee_raw:
        return _shared.errored_result("book_appointment.assigned_to_user_id is required")
    if not scheduled_at_path:
        return _shared.errored_result("book_appointment.scheduled_at_from is required")

    # Resolve the ISO datetime from the run answers.
    answers = (ctx.run_context or {}).get("answers") or {}
    key = scheduled_at_path.split(".", 1)[1] if scheduled_at_path.startswith("answers.") else scheduled_at_path
    scheduled_raw = answers.get(key)
    if not scheduled_raw:
        return NodeResult(
            next_edge_label="error",
            skip_reason="missing_scheduled_at",
            output={"path": scheduled_at_path},
        )
    try:
        scheduled_at = datetime.fromisoformat(str(scheduled_raw))
    except ValueError:
        return NodeResult(
            next_edge_label="error",
            skip_reason="unparseable_scheduled_at",
            output={"value": scheduled_raw},
        )

    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    title = channel_bridge.render_variables(
        title_template,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=_shared.channel_of(ctx),
    )

    if ctx.is_test:
        return NodeResult(
            next_edge_label="booked",
            output={
                "title": title,
                "scheduled_at": scheduled_at.isoformat(),
                "duration_minutes": duration_minutes,
                "assigned_to_user_id": str(assignee_raw),
                "test_mode": True,
            },
        )

    try:
        assignee_uuid = uuid.UUID(str(assignee_raw))
    except (TypeError, ValueError) as exc:
        return _shared.errored_result(f"invalid assigned_to_user_id: {exc}")

    try:
        from src.app.core.appointments.schemas import AppointmentCreate
        from src.app.core.appointments.service import create_appointment

        payload = AppointmentCreate(
            contact_id=ctx.run.contact_id,
            title=title,
            purpose=cfg.get("purpose"),
            scheduled_at=scheduled_at,
            duration_min=duration_minutes,
            location=cfg.get("location"),
            assigned_to_id=assignee_uuid,
            custom_data={},
        )
        appt = await create_appointment(
            ctx.session,
            org_id=ctx.run.org_id,
            current_user_id=assignee_uuid,
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001
        # 409 conflict from the service surfaces via HTTPException;
        # for the bot flow we treat any conflict-shaped error as busy.
        msg = str(exc).lower()
        if "409" in msg or "conflict" in msg or "busy" in msg:
            return NodeResult(
                next_edge_label="busy",
                skip_reason="slot_conflict",
                output={"scheduled_at": scheduled_at.isoformat(), "error": str(exc)},
            )
        return NodeResult(
            next_edge_label="error",
            skip_reason="appointment_service_rejected",
            output={"error": str(exc)},
        )

    return NodeResult(
        next_edge_label="booked",
        output={
            "appointment_id": str(appt.id),
            "title": title,
            "scheduled_at": scheduled_at.isoformat(),
            "duration_minutes": duration_minutes,
        },
    )


register_node(_NODE_TYPE, handle)
