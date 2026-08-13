"""Shared helpers for the message-node handlers (``tasks/chatbot-builder``
Step 7).

Kept out of the per-node files so each handler stays small +
focused. Not `_utils.py` — the pin-test allows helper files under
`core/` to hold SQL only if named `data_access.py`; these helpers
only compose ORM reads (via other DALs) + pure logic.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as _dal
from src.app.core.chatbots.channel_bridge import (
    is_within_wa_window,
    render_variables,
)
from src.app.core.chatbots.engine import NodeExecutionContext, NodeResult
from src.app.core.conversations.models import Conversation, ConversationChannel


async def load_conversation(
    session: AsyncSession, *, conversation_id: uuid.UUID | None
) -> Conversation | None:
    """Load the conversation row via DAL — kept as a re-export from
    _shared so node handlers can import all their helpers from one
    place."""
    return await _dal.load_conversation_for_bot(
        session, conversation_id=conversation_id
    )


async def load_contact_data(
    session: AsyncSession, *, contact_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """Minimal contact dict for variable rendering. Kept small so we
    don't leak the whole contact ORM object into templates."""
    if contact_id is None:
        return None
    from src.app.core.contacts import service as contacts_service

    contact = await contacts_service.get_contact(session, contact_id)
    if contact is None:
        return None
    full_name = contact.full_name or ""
    parts = full_name.split(None, 1) if full_name else []
    return {
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "full_name": full_name,
        "email": contact.email or "",
        "phone": contact.phone or "",
    }


def channel_of(ctx: NodeExecutionContext) -> str:
    """Read the inbound channel from the run's context; falls back to
    the conversation's channel when a full lookup is available."""
    return (ctx.run_context or {}).get("channel") or "whatsapp"


async def wa_window_open_or_take_session_expired(
    session: AsyncSession,
    *,
    conversation: Conversation | None,
) -> bool:
    """Return True iff the send is safe to dispatch on WhatsApp.
    False signals the caller to take the ``session_expired`` port."""
    if conversation is None:
        return True
    if conversation.channel != ConversationChannel.whatsapp:
        return True
    return await is_within_wa_window(session, conversation=conversation)


def is_resumed_from_park(ctx: NodeExecutionContext) -> bool:
    """The engine's resume_run flips this flag to True; handlers use
    it to interpret ``last_inbound_text`` as a reply to their parked
    prompt rather than the initial trigger."""
    return bool((ctx.run_context or {}).get("resumed_from_park"))


def clear_resume_flag() -> dict[str, Any]:
    """Handler helper: patch to merge into run.context on advance so
    the flag doesn't carry over to the NEXT node's handler."""
    return {"resumed_from_park": False}


def match_button_reply(
    inbound_text: str,
    buttons: list[dict[str, str]],
) -> str | None:
    """Given the customer's reply text, return the matching button's
    ``id`` (used as the outbound-edge label), or ``None``.

    Match precedence:
      1. Exact case-insensitive match on button ``title``.
      2. Case-insensitive prefix match on button ``title`` (customer
         typed "yes I do" for a "Yes" button).
      3. Numbered fallback for Baileys — customer types ``1`` / ``2``
         / ``3`` and we look up the corresponding button.
    """
    reply = (inbound_text or "").strip()
    if not reply:
        return None
    lowered = reply.lower()

    for btn in buttons:
        title = (btn.get("title") or "").strip().lower()
        if title and title == lowered:
            return btn["id"]

    for btn in buttons:
        title = (btn.get("title") or "").strip().lower()
        if title and lowered.startswith(title):
            return btn["id"]

    # Numbered fallback — "1", "1.", "1)", "reply 1", etc.
    for prefix in ("reply ", ""):
        if not lowered.startswith(prefix):
            continue
        remainder = lowered[len(prefix):].strip().rstrip(").")
        try:
            n = int(remainder)
        except ValueError:
            continue
        if 1 <= n <= len(buttons):
            return buttons[n - 1]["id"]

    return None


def errored_result(reason: str) -> NodeResult:
    """Handler helper — build an ``errored`` NodeResult that the
    engine records + marks the run errored."""
    return NodeResult(error=reason, skip_reason=None, output={"error": reason})


__all__ = [
    "channel_of",
    "clear_resume_flag",
    "errored_result",
    "is_resumed_from_park",
    "load_conversation",
    "load_contact_data",
    "match_button_reply",
    "wa_window_open_or_take_session_expired",
]
