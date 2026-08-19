"""Single AI Message node
(``tasks/chatbot-builder`` Step 10, wired live in
``tasks/ai-assistants`` Step 9).

Runs one turn of an AI Assistant inside a bot flow. Picks the
assistant via ``config['assistant_id']`` when present; otherwise
falls back to the org's first ACTIVE assistant so simple flows
work out of the box.

Config shape (accepted at save-time)::

    {
      "assistant_id": "<optional AI assistant uuid>",
      "system_prompt": "You are a helpful sales assistant for {{org.name}}.",
      "user_prompt_template": "The customer just said: {{run.last_inbound_text}}",
      "save_reply_to": "answers.ai_reply"
    }

Output ports:
  * ``sent`` — normal exit, reply captured in ``context_patch``.
  * ``error`` — no assistant available or the runtime failed.

The full conversation-continuity story (share the bot's parent
conversation with the AI-widget's persistence) is out of scope for
Step 9; the runtime creates its own preview-style conversation for
now. A future integration track wires the two together.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.ai_assistants.runtime import reply_once
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)

_NODE_TYPE = "single_ai_message"
_DEFAULT_SAVE_KEY = "answers.ai_reply"


async def _pick_assistant_id(
    session,
    *,
    org_id: uuid.UUID,
    configured_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Return the assistant id the node should invoke. Explicit
    config wins; otherwise the org's first active assistant."""
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


def _render_template(template: str, ctx: NodeExecutionContext) -> str:
    """Very small ``{{run.last_inbound_text}}`` substitution. Missing
    key renders as an empty string so a template change can't crash
    the runtime."""
    if not template:
        return ""
    last_inbound = str(ctx.run.context.get("last_inbound_text", "")) if ctx.run.context else ""
    return template.replace("{{run.last_inbound_text}}", last_inbound)


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

    # No session (test harness with mocked ctx) — can't look up.
    # Fall through to the no-assistant error path.
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
                    "/user/ai-assistants and set it to Active, or set "
                    "config.assistant_id explicitly."
                ),
            },
        )

    user_message = _render_template(
        str(cfg.get("user_prompt_template", "")),
        ctx,
    )
    if not user_message.strip():
        return NodeResult(
            next_edge_label="error",
            skip_reason="no_user_message",
            output={"reason": "user_prompt_template rendered empty"},
        )

    session_token = f"chatbot:{ctx.run.id}"
    try:
        reply = await reply_once(
            db=ctx.session,
            org_id=ctx.run.org_id,
            assistant_id=assistant_id,
            user_message=user_message,
            session_token=session_token,
            is_public=False,
        )
    except Exception as exc:  # noqa: BLE001 — keep bot flows alive
        return NodeResult(
            next_edge_label="error",
            skip_reason="runtime_error",
            output={"reason": f"AI runtime error: {exc}"},
        )

    save_to = str(cfg.get("save_reply_to") or _DEFAULT_SAVE_KEY)
    return NodeResult(
        next_edge_label="sent",
        context_patch={save_to: reply},
        output={"reply": reply, "assistant_id": str(assistant_id)},
    )


register_node(_NODE_TYPE, handle)
