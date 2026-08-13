"""Text Button node (``tasks/chatbot-builder`` Step 7).

Config shape::

    {
      "body": "👋 Hi there! ...",
      "buttons": [
        {"id": "interested", "title": "I'm interested"},
        {"id": "pricing",    "title": "See pricing"},
        {"id": "human",      "title": "Talk to a human"}
      ],
      "header_text": "Welcome",          # optional
      "footer_text": "Powered by CRM",   # optional
      "session_expired_template_id": null  # optional WA fallback (Step 5)
    }

Two-phase handler:

  * **First execution** — send the interactive-button message + park
    the run with ``park_key=("button_click", conversation_id)``.
  * **Resume from park** — match the customer's reply text against
    the button titles / numbered index, advance via the button's
    ``id`` as the outbound-edge label. No match → take the unlabeled
    default edge or end.
"""

from __future__ import annotations

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "text_button"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return _resolve_button_reply(ctx)
    return await _send_and_park(ctx)


async def _send_and_park(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    body_raw = str(cfg.get("body") or "")
    buttons = cfg.get("buttons") or []

    if not body_raw:
        return _shared.errored_result("text_button.body is required")
    if not isinstance(buttons, list) or not (1 <= len(buttons) <= 3):
        return _shared.errored_result("text_button.buttons must be a list of 1-3 items")
    for btn in buttons:
        if not isinstance(btn, dict) or "id" not in btn or "title" not in btn:
            return _shared.errored_result(
                "each button needs id + title"
            )
        title = str(btn["title"])
        if not title or len(title) > 20:
            return _shared.errored_result(
                "button title must be 1-20 characters (WA API limit)"
            )
    if len(body_raw) > 1024:
        return _shared.errored_result("text_button.body exceeds 1024 chars (WA API limit)")

    conversation = await _shared.load_conversation(
        ctx.session,
        conversation_id=ctx.run.conversation_id,
    )
    contact_data = await _shared.load_contact_data(
        ctx.session,
        contact_id=ctx.run.contact_id,
    )
    channel = _shared.channel_of(ctx)

    body = channel_bridge.render_variables(
        body_raw,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    # WhatsApp 24h window enforcement (Decision §H3).
    if not await _shared.wa_window_open_or_take_session_expired(
        ctx.session, conversation=conversation
    ):
        return NodeResult(
            next_edge_label="session_expired",
            skip_reason="wa_session_window_closed",
            output={"channel": channel, "reason": "wa_session_window_closed"},
        )

    if conversation is None:
        # Test-fire runs may have no conversation — just record the
        # transcript entry and park.
        transcript = {
            "send_kind": "interactive_buttons",
            "body": body,
            "buttons": buttons,
            "test_mode": True,
            "no_conversation": True,
        }
    else:
        transcript = await channel_bridge.send_bot_interactive_buttons(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            body_text=body,
            buttons=buttons,
            header_text=cfg.get("header_text"),
            footer_text=cfg.get("footer_text"),
            is_test=ctx.is_test,
        )

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(
        park_key=("button_click", conv_id),
        output=transcript,
    )


def _resolve_button_reply(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    buttons = cfg.get("buttons") or []
    reply_text = str((ctx.run_context or {}).get("last_inbound_text") or "")

    edge_label = _shared.match_button_reply(reply_text, buttons)

    context_patch = _shared.clear_resume_flag()

    if edge_label is None:
        return NodeResult(
            # Follow the unlabeled default edge if the graph has one,
            # else the engine's find-next falls through to the first
            # unlabeled outbound.
            next_edge_label=None,
            context_patch=context_patch,
            output={
                "resume_reply": reply_text,
                "matched": None,
                "note": "no button matched; taking default edge",
            },
        )

    return NodeResult(
        next_edge_label=edge_label,
        context_patch=context_patch,
        output={"resume_reply": reply_text, "matched": edge_label},
    )


register_node(_NODE_TYPE, handle)
