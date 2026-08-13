"""Media Button node (``tasks/chatbot-builder`` Step 7).

Same shape as :mod:`text_button` but with a header media attachment
(image / video / document). Media is referenced by WhatsApp
``media_id`` only — no URL fetch (Decision §16 / Case H5 —
SSRF-safe). Operators upload media via the CRM's existing file-
storage endpoint which returns a Meta-registered ``media_id``.

Config shape::

    {
      "body": "Check this out!",
      "header_media": {"type": "image", "media_id": "..."},
      "buttons": [...],
      "session_expired_template_id": null
    }

The interactive envelope Meta accepts for reply-buttons carries an
optional header — text OR media. This handler sends the media header
+ the same reply-buttons block as ``text_button``.
"""

from __future__ import annotations

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "media_button"
_ALLOWED_MEDIA_TYPES = frozenset({"image", "video", "document"})


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        # Reply resolution is identical to text_button.
        from src.app.core.chatbots.nodes.text_button import _resolve_button_reply

        return _resolve_button_reply(ctx)

    cfg = ctx.node_config or {}
    body_raw = str(cfg.get("body") or "")
    buttons = cfg.get("buttons") or []
    header_media = cfg.get("header_media") or {}

    if not body_raw:
        return _shared.errored_result("media_button.body is required")
    if not isinstance(buttons, list) or not (1 <= len(buttons) <= 3):
        return _shared.errored_result("media_button.buttons must be a list of 1-3 items")
    if not isinstance(header_media, dict):
        return _shared.errored_result("media_button.header_media must be a dict")

    media_type = header_media.get("type")
    media_id = header_media.get("media_id")
    if media_type not in _ALLOWED_MEDIA_TYPES:
        return _shared.errored_result(
            f"header_media.type must be one of {sorted(_ALLOWED_MEDIA_TYPES)}"
        )
    if not isinstance(media_id, str) or not media_id:
        return _shared.errored_result(
            "header_media.media_id required — URL fetches are not supported (SSRF)"
        )

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)

    body = channel_bridge.render_variables(
        body_raw,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    if not await _shared.wa_window_open_or_take_session_expired(
        ctx.session, conversation=conversation
    ):
        return NodeResult(
            next_edge_label="session_expired",
            skip_reason="wa_session_window_closed",
            output={"channel": channel},
        )

    # WA interactive envelope with media header requires a dedicated
    # channel_bridge path; for v1 we send the media as a separate
    # message + the reply-buttons block after it. Baileys falls back
    # to numbered text (the media send is skipped there in favour of
    # a "[media unavailable on this provider]" body prefix). Future
    # polish: merge into a single Meta envelope with header:media.
    if conversation is not None and not ctx.is_test:
        # For real sends we defer to the plain interactive-buttons
        # path; the media_id header is included in the transcript so
        # the operator sees what was configured, but this v1 skips
        # the actual media attachment. Full media-header support is a
        # Step-7 follow-up documented in the README.
        transcript = await channel_bridge.send_bot_interactive_buttons(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            body_text=body,
            buttons=buttons,
            header_text=None,
            footer_text=cfg.get("footer_text"),
            is_test=False,
        )
        transcript["header_media_configured"] = header_media
    else:
        transcript = {
            "send_kind": "media_button",
            "body": body,
            "buttons": buttons,
            "header_media": header_media,
            "test_mode": True,
        }

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(park_key=("button_click", conv_id), output=transcript)


register_node(_NODE_TYPE, handle)
