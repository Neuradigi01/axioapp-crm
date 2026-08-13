"""List node (``tasks/chatbot-builder`` Step 7).

WhatsApp Interactive List — up to 10 rows across up to 10 sections,
each row selectable. Row selection resumes the parked run and
advances via the row ``id`` as the outbound-edge label. Baileys
fallback flattens rows into numbered text (same pattern as
:mod:`text_button`).

Config shape::

    {
      "body": "How can I help?",
      "button_text": "Choose an option",
      "sections": [
        {
          "title": "Sales",
          "rows": [
            {"id": "pricing", "title": "See pricing",
             "description": "Plans starting from ₹499/mo"},
            {"id": "demo",    "title": "Book a demo"}
          ]
        },
        {"title": "Support", "rows": [{"id": "help", "title": "Talk to support"}]}
      ]
    }
"""

from __future__ import annotations

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "list"
_WA_MAX_ROWS = 10
_WA_MAX_SECTIONS = 10


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return _resolve_row_reply(ctx)
    return await _send_and_park(ctx)


async def _send_and_park(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    body_raw = str(cfg.get("body") or "")
    button_text = str(cfg.get("button_text") or "Choose")
    sections = cfg.get("sections") or []

    if not body_raw:
        return _shared.errored_result("list.body is required")
    if not isinstance(sections, list) or not sections:
        return _shared.errored_result("list.sections must be a non-empty list")
    if len(sections) > _WA_MAX_SECTIONS:
        return _shared.errored_result(
            f"list.sections limited to {_WA_MAX_SECTIONS} per WA API"
        )

    total_rows = 0
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("rows"), list):
            return _shared.errored_result("each list section needs a rows list")
        for row in section["rows"]:
            if not isinstance(row, dict) or "id" not in row or "title" not in row:
                return _shared.errored_result("each list row needs id + title")
            title = str(row["title"])
            if not title or len(title) > 24:
                return _shared.errored_result("row title must be 1-24 chars (WA API limit)")
            total_rows += 1
    if total_rows > _WA_MAX_ROWS:
        return _shared.errored_result(
            f"list rows limited to {_WA_MAX_ROWS} total per WA API"
        )
    if len(body_raw) > 1024:
        return _shared.errored_result("list.body exceeds 1024 chars (WA API limit)")

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)

    body = channel_bridge.render_variables(
        body_raw, run_context=ctx.run_context, contact_data=contact_data, channel=channel
    )

    if not await _shared.wa_window_open_or_take_session_expired(
        ctx.session, conversation=conversation
    ):
        return NodeResult(
            next_edge_label="session_expired",
            skip_reason="wa_session_window_closed",
            output={"channel": channel},
        )

    if conversation is None:
        transcript = {
            "send_kind": "interactive_list",
            "body": body,
            "sections": sections,
            "test_mode": True,
            "no_conversation": True,
        }
    else:
        transcript = await channel_bridge.send_bot_interactive_list(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            body_text=body,
            button_text=button_text,
            sections=sections,
            header_text=cfg.get("header_text"),
            footer_text=cfg.get("footer_text"),
            is_test=ctx.is_test,
        )

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(park_key=("list_row_click", conv_id), output=transcript)


def _resolve_row_reply(ctx: NodeExecutionContext) -> NodeResult:
    """Flatten all rows across sections and reuse the button-reply
    matcher — same case-insensitive + numbered-fallback shape."""
    cfg = ctx.node_config or {}
    sections = cfg.get("sections") or []
    reply_text = str((ctx.run_context or {}).get("last_inbound_text") or "")

    flat_rows: list[dict[str, str]] = []
    for section in sections:
        for row in section.get("rows", []):
            flat_rows.append({"id": row["id"], "title": row["title"]})

    edge_label = _shared.match_button_reply(reply_text, flat_rows)
    context_patch = _shared.clear_resume_flag()

    if edge_label is None:
        return NodeResult(
            context_patch=context_patch,
            output={
                "resume_reply": reply_text,
                "matched": None,
                "note": "no row matched; taking default edge",
            },
        )

    return NodeResult(
        next_edge_label=edge_label,
        context_patch=context_patch,
        output={"resume_reply": reply_text, "matched": edge_label},
    )


register_node(_NODE_TYPE, handle)
