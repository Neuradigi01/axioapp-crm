"""Create Task node (``tasks/chatbot-builder`` Step 10).

Creates a follow-up task via :func:`core.tasks.service.create_task`.
Passes ``can_assign_others=True`` because the bot is acting as a
system agent, not a specific staff member — the target assignee
is whoever the config says (bot creator's own team, contact
owner, or a specific user).

Config shape::

    {
      "title": "Follow up with {{contact.full_name}} re {{answers.interest}}",
      "description": "",
      "assignee_mode": "specific" | "contact_owner" | "bot_creator",
      "assignee_user_id": "<uuid>",   # required for specific
      "due_in_hours": 24,
      "priority": "medium"            # low | medium | high
    }

Output ports: ``created`` (default), ``error``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "create_task"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    title_template = str(cfg.get("title") or "")
    description = str(cfg.get("description") or "")
    assignee_mode = str(cfg.get("assignee_mode") or "specific")
    assignee_raw = cfg.get("assignee_user_id")
    due_in_hours = int(cfg.get("due_in_hours") or 24)
    priority = str(cfg.get("priority") or "medium")

    if not title_template:
        return _shared.errored_result("create_task.title is required")
    if priority not in {"low", "medium", "high"}:
        return _shared.errored_result("create_task.priority must be low|medium|high")

    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    title = channel_bridge.render_variables(
        title_template,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=_shared.channel_of(ctx),
    )

    # Resolve assignee.
    assignee_id: uuid.UUID | None = None
    if assignee_mode == "specific":
        if not assignee_raw:
            return _shared.errored_result(
                "create_task.assignee_user_id required for specific mode"
            )
        try:
            assignee_id = uuid.UUID(str(assignee_raw))
        except (TypeError, ValueError) as exc:
            return _shared.errored_result(f"invalid assignee_user_id: {exc}")
    elif assignee_mode == "contact_owner":
        # Read from the loaded contact's assigned_to_id if present.
        if ctx.run.contact_id is None:
            return NodeResult(
                skip_reason="no_contact_on_run",
                output={"reason": "contact_owner mode needs a contact"},
            )
        # Load fresh — contact_data is a small dict without assigned_to_id.
        from src.app.core.chatbots import data_access as _dal

        contact = await _dal.load_contact_for_bot_write(
            ctx.session, org_id=ctx.run.org_id, contact_id=ctx.run.contact_id
        )
        if contact is None or contact.assigned_to_id is None:
            return NodeResult(
                skip_reason="no_contact_owner",
                output={"reason": "contact has no owner assigned"},
            )
        assignee_id = contact.assigned_to_id
    elif assignee_mode == "bot_creator":
        # Bot's created_by_user_id is on the bot row. Loaded via
        # engine's bot fetch in ctx.bot.
        creator = getattr(ctx.bot, "created_by_user_id", None)
        if creator is None:
            return NodeResult(
                skip_reason="no_bot_creator",
                output={"reason": "bot has no created_by_user_id"},
            )
        assignee_id = creator
    else:
        return _shared.errored_result(
            f"create_task.assignee_mode {assignee_mode!r} not supported"
        )

    due_at = datetime.now(UTC) + timedelta(hours=due_in_hours)

    if ctx.is_test:
        return NodeResult(
            next_edge_label="created",
            output={
                "title": title,
                "assigned_to_id": str(assignee_id),
                "due_at": due_at.isoformat(),
                "priority": priority,
                "test_mode": True,
            },
        )

    try:
        from src.app.core.tasks.schemas import TaskCreate
        from src.app.core.tasks.service import create_task as _create_task_service

        payload = TaskCreate(
            title=title,
            description=description or None,
            due_at=due_at,
            assigned_to_id=assignee_id,
            related_entity_type="contact" if ctx.run.contact_id else None,
            related_entity_id=ctx.run.contact_id,
            priority=priority,
            custom_data={},
        )
        task = await _create_task_service(
            ctx.session,
            org_id=ctx.run.org_id,
            current_user_id=assignee_id,
            payload=payload,
            can_assign_others=True,
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            next_edge_label="error",
            skip_reason="task_service_rejected",
            output={"error": str(exc)},
        )

    return NodeResult(
        next_edge_label="created",
        output={
            "task_id": str(task.id),
            "title": title,
            "assigned_to_id": str(assignee_id),
            "due_at": due_at.isoformat(),
        },
    )


register_node(_NODE_TYPE, handle)
