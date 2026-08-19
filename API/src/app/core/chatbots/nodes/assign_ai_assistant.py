"""Assign AI Assistant node
(``tasks/chatbot-builder`` Step 10, wired live in
``tasks/ai-assistants`` Step 9).

Where :mod:`single_ai_message` is one-shot, this node hands the
conversation over to an ongoing AI Assistant — every subsequent
inbound message on the parent conversation is passed to the same
assistant until the bot flow's ``end_bot`` node fires or a
human takes over.

V1 wire: sets ``ctx.run.context['ai_assistant_id'] = <picked>``
and returns ``handed_off``. The engine's inbound-matching loop
(Step 5 of the chatbot-builder track) checks this key; if set,
subsequent inbounds are routed to
:func:`core.ai_assistants.runtime.reply_once` instead of the next
bot node. The engine-side loop is landing in the follow-on
integration track; this node's job is to record the handoff so
the loop has something to key on when it ships.

Config shape (accepted at save-time)::

    {
      "assistant_id": "<optional AI assistant uuid>",
      "handoff_on_low_confidence": true,
      "max_turns": 8
    }

Output ports:
  * ``handed_off`` — assistant picked + recorded on run.context.
  * ``error`` — no assistant available.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)

_NODE_TYPE = "assign_ai_assistant"


async def _pick_assistant_id(
    session,
    *,
    org_id: uuid.UUID,
    configured_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if configured_id is not None:
        return configured_id
    stmt = (
        select(AiAssistant.id)
        .where(
            AiAssistant.org_id == org_id,
            AiAssistant.status == AiAssistantStatus.active,
        )
        .order_by(AiAssistant.created_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    configured_raw = cfg.get("assistant_id")
    configured_id: uuid.UUID | None = None
    if configured_raw:
        try:
            configured_id = uuid.UUID(str(configured_raw))
        except ValueError:
            return NodeResult(
                next_edge_label="error",
                skip_reason="bad_assistant_id",
                output={"reason": f"invalid assistant_id: {configured_raw!r}"},
            )

    # No session (test harness) — fall through to the no-assistant
    # error path.
    assistant_id: uuid.UUID | None = None
    if ctx.session is not None:
        assistant_id = await _pick_assistant_id(
            ctx.session,
            org_id=ctx.run.org_id,
            configured_id=configured_id,
        )
    if assistant_id is None:
        return NodeResult(
            next_edge_label="error",
            skip_reason="no_ai_assistant_available",
            output={
                "reason": (
                    "No active AI assistant found for this org. Create one at "
                    "/user/ai-assistants and set it to Active."
                ),
            },
        )

    return NodeResult(
        next_edge_label="handed_off",
        context_patch={
            "ai_assistant_id": str(assistant_id),
            "ai_assistant_max_turns": int(cfg.get("max_turns", 8)),
        },
        output={"assistant_id": str(assistant_id)},
    )


register_node(_NODE_TYPE, handle)
