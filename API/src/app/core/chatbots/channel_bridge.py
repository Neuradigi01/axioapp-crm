"""Channel-agnostic helpers shared by the chatbot runtime.

Step 6 lands only the WhatsApp 24h session-window check. Steps 7-10
extend this module with the actual interactive-send methods
(``send_text_button``, ``send_list``, ``send_template``, …) and the
per-channel escaping used by the answer-variable resolver.

The 24h helper reads :attr:`Conversation.last_customer_message_at`
(populated by ``conversations/service.py:receive_webhook``). NULL
means the customer has never sent — treat as OUTSIDE the window so
a fresh bot flow requires a template first send.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
)


# WhatsApp's customer-service window is 24 hours after the customer's
# last inbound. Free-form outbound outside that window is a Meta policy
# violation → account penalties. All send-capable WA node handlers
# check this before dispatch (Step 7 onwards).
_WA_SESSION_WINDOW = timedelta(hours=24)


async def is_within_wa_window(
    session: AsyncSession,
    *,
    conversation: Conversation,
    now: datetime | None = None,
) -> bool:
    """True iff the WhatsApp 24h customer-service window is open on
    the given conversation. Non-WA conversations always return True —
    the check is a no-op for email + other channels."""
    if conversation.channel != ConversationChannel.whatsapp:
        return True

    last = conversation.last_customer_message_at
    if last is None:
        return False

    reference = now or datetime.now(UTC)
    return (reference - last) < _WA_SESSION_WINDOW


async def is_within_wa_window_by_conv_id(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Convenience wrapper that loads the conversation row itself.
    Prefer :func:`is_within_wa_window` when the caller already holds
    the loaded object."""
    from sqlalchemy import select

    conv = (
        await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conv is None:
        return False
    return await is_within_wa_window(session, conversation=conv, now=now)


# --- Variable rendering ---------------------------------------------------
#
# Handlers resolve ``{{answers.<node_id>}}``, ``{{contact.<field>}}``,
# and ``{{run.<key>}}`` via :func:`render_variables` before sending.
# Missing variables render as empty strings — matches the templates
# variable engine's fallback (Case #24).

import html as _html
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def render_variables(
    text: str,
    *,
    run_context: dict[str, Any],
    contact_data: dict[str, Any] | None = None,
    channel: str = "whatsapp",
) -> str:
    """Resolve ``{{answers.<id>}}`` / ``{{contact.<field>}}`` /
    ``{{run.<key>}}`` in a message body.

    Per-channel escaping applies at the render boundary (Case M4 —
    no XSS via customer text). WhatsApp payloads travel as JSON and
    httpx handles string-escape at serialize time, so WA rendering
    only strips control characters that would break the client UI.
    Email HTML bodies get :func:`html.escape` on every substituted
    value.
    """
    if not text or "{{" not in text:
        return text or ""

    answers = run_context.get("answers") or {}
    run_scope = {
        "conversation_id": run_context.get("conversation_id"),
        "contact_id": run_context.get("contact_id"),
        "last_inbound_text": run_context.get("last_inbound_text") or "",
        "channel": run_context.get("channel") or "",
    }
    contact_scope = contact_data or {}

    def _lookup(key: str) -> str:
        parts = key.split(".")
        if not parts:
            return ""
        head, rest = parts[0], parts[1:]
        if head == "answers":
            if not rest:
                return ""
            value = answers.get(rest[0], "")
            return str(value or "")
        if head == "contact":
            if not rest:
                return ""
            value = contact_scope.get(rest[0], "")
            return str(value or "")
        if head == "run":
            if not rest:
                return ""
            value = run_scope.get(rest[0], "")
            return str(value or "")
        return ""

    def _replace(match: re.Match[str]) -> str:
        raw = _lookup(match.group(1))
        return _escape_for_channel(raw, channel=channel)

    return _VARIABLE_RE.sub(_replace, text)


def _escape_for_channel(value: str, *, channel: str) -> str:
    """Per-channel safety escape. Values coming from
    ``answers.*`` originate as raw customer text — always sanitize
    before rendering into an outbound payload."""
    if channel == "email":
        return _html.escape(value, quote=True)
    # WhatsApp: strip control characters that would break the client
    # UI. JSON string-escape is handled by httpx at serialize time.
    return "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 0x20)


# --- Outbound send helpers ------------------------------------------------
#
# Bot outbounds bypass ``conversations/service.py:send_outbound``
# (which is the human-authored path with ``chatbot_run_id IS NULL``
# semantics — driving the Step-6 human-takeover hook). Bot outbounds
# always set ``chatbot_run_id`` and ``sender_user_id=NULL``.


async def send_bot_text(
    session: AsyncSession,
    *,
    conversation: Conversation,
    run_id: uuid.UUID,
    text: str,
    is_test: bool = False,
) -> dict[str, Any]:
    """Send a plain-text message from a bot run. Returns a small
    dict for the step-run's ``output`` (transcript entry) — includes
    the persisted message id on real sends, ``None`` on test mode."""
    if is_test:
        return {"send_kind": "text", "text": text, "test_mode": True}

    ref = await _dispatch_channel_send(
        session,
        conversation=conversation,
        text=text,
        interactive=None,
        attachments=[],
    )
    msg_id = await _persist_bot_outbound(
        session,
        conversation=conversation,
        run_id=run_id,
        text=text,
        interactive_payload=None,
        channel_message_id=ref.channel_message_id,
    )
    return {"send_kind": "text", "text": text, "message_id": str(msg_id)}


async def send_bot_interactive_buttons(
    session: AsyncSession,
    *,
    conversation: Conversation,
    run_id: uuid.UUID,
    body_text: str,
    buttons: list[dict[str, str]],
    header_text: str | None = None,
    footer_text: str | None = None,
    is_test: bool = False,
) -> dict[str, Any]:
    """Send WhatsApp reply-buttons (max 3). On Baileys the adapter
    raises ``WhatsAppSendError`` for interactive — we catch that and
    fall back to a numbered-text send so the flow still works."""
    interactive_payload = {
        "kind": "reply_buttons",
        "body": body_text,
        "buttons": [{"id": b["id"], "title": b["title"]} for b in buttons],
    }
    if header_text:
        interactive_payload["header"] = {"text": header_text}
    if footer_text:
        interactive_payload["footer"] = footer_text

    if is_test:
        return {
            "send_kind": "interactive_buttons",
            "body": body_text,
            "buttons": buttons,
            "test_mode": True,
        }

    try:
        ref = await _dispatch_channel_send(
            session,
            conversation=conversation,
            text=body_text,
            interactive=interactive_payload,
            attachments=[],
        )
        fallback_used = False
    except Exception as exc:  # noqa: BLE001
        # Baileys / unsupported provider — fall back to numbered text
        # (per Decision §5's channel matrix).
        if not _is_interactive_unsupported(exc):
            raise
        numbered_body = _numbered_text_fallback(body_text, buttons)
        ref = await _dispatch_channel_send(
            session,
            conversation=conversation,
            text=numbered_body,
            interactive=None,
            attachments=[],
        )
        body_text = numbered_body
        interactive_payload["fallback"] = "numbered_text"
        fallback_used = True

    msg_id = await _persist_bot_outbound(
        session,
        conversation=conversation,
        run_id=run_id,
        text=body_text,
        interactive_payload=interactive_payload,
        channel_message_id=ref.channel_message_id,
    )
    return {
        "send_kind": "interactive_buttons",
        "body": body_text,
        "buttons": buttons,
        "message_id": str(msg_id),
        "fallback_used": fallback_used,
    }


async def send_bot_interactive_list(
    session: AsyncSession,
    *,
    conversation: Conversation,
    run_id: uuid.UUID,
    body_text: str,
    button_text: str,
    sections: list[dict[str, Any]],
    header_text: str | None = None,
    footer_text: str | None = None,
    is_test: bool = False,
) -> dict[str, Any]:
    """Send WhatsApp list message (up to 10 rows). Baileys fallback
    is the same numbered-text pattern as buttons — rows across all
    sections are flattened + numbered."""
    interactive_payload = {
        "kind": "list",
        "body": body_text,
        "button_text": button_text,
        "sections": sections,
    }
    if header_text:
        interactive_payload["header"] = {"text": header_text}
    if footer_text:
        interactive_payload["footer"] = footer_text

    if is_test:
        return {
            "send_kind": "interactive_list",
            "body": body_text,
            "sections": sections,
            "test_mode": True,
        }

    try:
        ref = await _dispatch_channel_send(
            session,
            conversation=conversation,
            text=body_text,
            interactive=interactive_payload,
            attachments=[],
        )
        fallback_used = False
    except Exception as exc:  # noqa: BLE001
        if not _is_interactive_unsupported(exc):
            raise
        flat_rows: list[dict[str, str]] = []
        for section in sections:
            for row in section.get("rows", []):
                flat_rows.append({"id": row["id"], "title": row["title"]})
        numbered_body = _numbered_text_fallback(body_text, flat_rows)
        ref = await _dispatch_channel_send(
            session,
            conversation=conversation,
            text=numbered_body,
            interactive=None,
            attachments=[],
        )
        body_text = numbered_body
        interactive_payload["fallback"] = "numbered_text"
        fallback_used = True

    msg_id = await _persist_bot_outbound(
        session,
        conversation=conversation,
        run_id=run_id,
        text=body_text,
        interactive_payload=interactive_payload,
        channel_message_id=ref.channel_message_id,
    )
    return {
        "send_kind": "interactive_list",
        "body": body_text,
        "sections": sections,
        "message_id": str(msg_id),
        "fallback_used": fallback_used,
    }


# --- Internals ------------------------------------------------------------


def _numbered_text_fallback(body: str, options: list[dict[str, str]]) -> str:
    """Turn a body + option list into numbered text so operators on
    Baileys still get a working flow. Reply parsing (customer types
    ``1``, ``2``, or the label) lives on the bot node handler."""
    lines = [body, ""]
    for idx, opt in enumerate(options, start=1):
        title = opt.get("title") or opt.get("id") or "Option"
        lines.append(f"Reply {idx} for {title}")
    return "\n".join(lines)


def _is_interactive_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "interactive" in msg and "cloud api provider" in msg


async def _dispatch_channel_send(
    session: AsyncSession,
    *,
    conversation: Conversation,
    text: str,
    interactive: dict[str, Any] | None,
    attachments: list[dict[str, Any]],
):
    """Resolve the right adapter for the conversation's channel and
    dispatch the send. Bot-outbound path — bypasses the block-list
    pre-flight in ``send_outbound`` because bot flows on blocked
    numbers can't happen (contact opt-out is checked upstream in
    the trigger matcher)."""
    from src.app.core.conversations.adapters.whatsapp import resolve_whatsapp_adapter
    from src.app.core.conversations.registry import resolve

    if conversation.channel == ConversationChannel.whatsapp:
        adapter = await resolve_whatsapp_adapter(
            session,
            phone_id=getattr(conversation, "received_via_phone_id", None),
        )
    else:
        adapter = resolve(conversation.channel)

    send_kwargs: dict[str, Any] = {
        "org_id": conversation.org_id,
        "external_id": conversation.external_id,
        "text": text,
        "attachments": attachments,
    }
    if interactive is not None:
        send_kwargs["interactive"] = interactive
    return await adapter.send(**send_kwargs)


async def _persist_bot_outbound(
    session: AsyncSession,
    *,
    conversation: Conversation,
    run_id: uuid.UUID,
    text: str,
    interactive_payload: dict[str, Any] | None,
    channel_message_id: str | None,
) -> uuid.UUID:
    """Insert the outbound Message row tagged with ``chatbot_run_id``.
    Layered-architecture exception: this helper stages the row via
    ``session.add``; it lives in ``channel_bridge`` (a helper module,
    same shape as ``core/integrations/whatsapp/auto_reply.py``)
    rather than :mod:`chatbots.data_access` because it composes an
    ORM object across two modules and commits its own transaction."""
    from datetime import UTC, datetime

    from src.app.core.conversations.models import Message, MessageDirection

    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=text,
        attachments=[],
        interactive_payload=interactive_payload,
        channel_message_id=channel_message_id,
        payload={"authored_by": "chatbot"},
        chatbot_run_id=run_id,
        sent_at=datetime.now(UTC),
    )
    session.add(msg)
    conversation.last_message_at = msg.sent_at
    await session.commit()
    await session.refresh(msg)
    return msg.id


__all__: list[str] = [
    "is_within_wa_window",
    "is_within_wa_window_by_conv_id",
    "render_variables",
    "send_bot_text",
    "send_bot_interactive_buttons",
    "send_bot_interactive_list",
]
