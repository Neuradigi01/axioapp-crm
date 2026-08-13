"""Chatbot execution engine — Step 5 stub, Step 6 fills in the
step-processor / wait / resume / cap logic.

At this step the engine's only job is :func:`start_run`, which
inserts a ``ChatbotRun`` row and returns it. Step 6 will:

  * enqueue the first node's :class:`process_step` Celery task,
  * apply per-conversation + per-org meter increments (Decision §9),
  * handle wait/park/resume,
  * hook human-takeover cancel into ``send_outbound``.

Kept minimal here so :mod:`core.chatbots.trigger_matcher` can call
``engine.start_run`` today without waiting for the full runtime.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots.models import Chatbot, ChatbotRun

logger = logging.getLogger(__name__)


async def start_run(
    session: AsyncSession,
    *,
    bot: Chatbot,
    event: dict[str, Any],
) -> ChatbotRun:
    """Create a ``ChatbotRun`` row for the winning bot and its
    triggering inbound message. Step 6 will extend this to enqueue
    the first-node Celery task; today it only persists the run so
    the idempotency check in the matcher (Case #1) has something to
    find on the next inbound.

    ``event`` is the bus envelope from Step 4's publish. All fields
    are expected present (org_id, conversation_id, contact_id,
    message_id, text, is_first_message, direction, channel).
    """
    conversation_id = _uuid_or_none(event.get("conversation_id"))
    contact_id = _uuid_or_none(event.get("contact_id"))
    message_id = _uuid_or_none(event.get("message_id"))

    run = ChatbotRun(
        org_id=bot.org_id,
        chatbot_id=bot.id,
        chatbot_version=bot.version_number,
        conversation_id=conversation_id,
        contact_id=contact_id,
        lead_id=None,
        status="running",
        context={
            "conversation_id": str(conversation_id) if conversation_id else None,
            "contact_id": str(contact_id) if contact_id else None,
            "last_inbound_message_id": str(message_id) if message_id else None,
            "last_inbound_text": event.get("text"),
            "channel": event.get("channel"),
            "is_first_message": bool(event.get("is_first_message")),
            "answers": {},
        },
        is_test=False,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    await session.refresh(run)
    logger.info(
        "chatbots.engine.run_started run=%s bot=%s conv=%s msg=%s",
        run.id,
        bot.id,
        conversation_id,
        message_id,
    )
    return run


def _uuid_or_none(raw: Any) -> uuid.UUID | None:
    """Best-effort UUID parse — the bus envelope carries string ids."""
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None
