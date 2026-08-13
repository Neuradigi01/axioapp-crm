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


__all__: list[str] = [
    "is_within_wa_window",
    "is_within_wa_window_by_conv_id",
]
