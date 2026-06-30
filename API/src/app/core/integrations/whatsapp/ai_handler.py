"""WhatsApp AI dispatch + handover pipeline
(whatsapp-platform-upgrade Step 19).

Single entry point — :func:`dispatch_ai_response` — invoked from
``receive_webhook`` when an inbound message lands on a conversation
with ``ai_handling=true``.

Pipeline:

  1. Skip if the message body looks like a handover phrase (operator
     keyword list). Flip the conversation to human + tag for triage.
  2. Otherwise build the LLM context (recent turns) and call
     ``core.ai.whatsapp_integration.generate_response``.
  3. If the response's confidence is below the org threshold OR the
     LLM itself signalled handover, escalate.
  4. Else send the AI reply through the WhatsApp adapter + persist
     the outbound row with ``payload.author = 'ai'`` so the frontend
     bubble renders the 🤖 badge.

Handover side-effects:

  * ``conversation.ai_handling = false``
  * Conversation gets a system "ai_escalated" hint stored on the
    outbound message's `payload` (Step 20 analytics reads it).
  * Step-18's assignment engine runs immediately to pick a human
    if the conversation is unassigned.

All exceptions are caught; the inbound webhook handler is unaffected
by AI failures.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.ai.whatsapp_integration import (
    AIResponse,
    generate_response,
    history_from_messages,
)
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.models import (
    Conversation,
    Message,
    MessageDirection,
)
from src.app.core.integrations.whatsapp.connect import get_active_config

logger = logging.getLogger(__name__)


_RECENT_TURNS = 20


def _matches_handover_keyword(text: str | None, keywords: list[str]) -> bool:
    """Case-insensitive substring scan over the operator's handover
    phrase list. Used as the first escalation gate before we even
    call the LLM — saves a roundtrip when the customer explicitly
    asks for a human."""
    if not text or not keywords:
        return False
    lowered = text.lower()
    return any(kw and kw.lower() in lowered for kw in keywords)


async def _send_ai_reply(
    session: AsyncSession,
    *,
    conversation: Conversation,
    response: AIResponse,
) -> Message | None:
    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        text=response.text,
        attachments=[],
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=response.text,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "author": "ai",
            "ai_confidence": response.confidence,
            "ai_metadata": response.metadata,
            "adapter_ref": ref.channel_message_id,
        },
        sent_at=sent_at,
    )
    session.add(msg)
    conversation.last_message_at = sent_at
    await session.commit()
    await session.refresh(msg)
    await audit.log(
        "conversations.ai_reply_sent",
        entity_type="conversation",
        entity_id=conversation.id,
        after={
            "confidence": response.confidence,
            "message_id": str(msg.id),
        },
    )
    return msg


async def _handover_to_human(
    session: AsyncSession,
    *,
    conversation: Conversation,
    reason: str,
) -> None:
    """Turn off AI handling + audit + invoke the assignment engine if
    the conversation is currently unassigned. Idempotent on repeat
    handovers — flipping `ai_handling` that's already False is a
    no-op."""
    if conversation.ai_handling:
        conversation.ai_handling = False
        await session.commit()
        await session.refresh(conversation)

    await audit.log(
        "conversations.ai_escalated",
        entity_type="conversation",
        entity_id=conversation.id,
        after={"reason": reason},
    )

    if conversation.assigned_to_id is None:
        # Reuse Step-18's pipeline so escalation lands on the right
        # staff member without duplicating routing logic here.
        try:
            from src.app.core.integrations.whatsapp.assignment_engine import (
                dispatch_assignment,
            )

            await dispatch_assignment(session, conversation=conversation)
        except Exception:
            logger.exception(
                "ai_handler: assignment after handover failed for conv %s",
                conversation.id,
            )


async def dispatch_ai_response(
    session: AsyncSession,
    *,
    conversation: Conversation,
    inbound_text: str | None,
) -> uuid.UUID | None:
    """Run the AI dispatch pipeline for a single inbound message.

    Returns the AI message id (when a reply was sent) or None
    (handover / no-op). Failures are caught + logged."""
    if not inbound_text:
        return None

    # Load org-wide settings — system prompt, handover keywords,
    # confidence threshold. RLS-scoped via `get_active_config`.
    try:
        bundle = await get_active_config(session)
    except Exception:
        logger.exception("ai_handler: settings lookup failed")
        return None
    if bundle is None:
        return None
    _, config = bundle

    # Stage 1 — explicit handover phrase short-circuits the LLM call.
    if _matches_handover_keyword(inbound_text, list(config.ai_handover_keywords or [])):
        await _handover_to_human(session, conversation=conversation, reason="keyword")
        return None

    # Stage 2 — pull recent turns + invoke the LLM.
    msgs = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.asc())
                .limit(_RECENT_TURNS * 2)
            )
        )
        .scalars()
        .all()
    )
    history = history_from_messages(msgs, max_turns=_RECENT_TURNS)

    try:
        response = await generate_response(
            system_prompt=config.ai_system_prompt,
            history=history,
            latest_inbound_text=inbound_text,
        )
    except Exception:
        logger.exception("ai_handler: generate_response raised")
        await _handover_to_human(
            session,
            conversation=conversation,
            reason="ai_invocation_failed",
        )
        return None

    threshold = float(config.ai_confidence_threshold or 0.6)
    if response.handover_requested or response.confidence < threshold:
        await _handover_to_human(
            session,
            conversation=conversation,
            reason=(
                "ai_requested"
                if response.handover_requested
                else f"low_confidence:{response.confidence:.2f}"
            ),
        )
        return None

    # Stage 3 — send the reply.
    try:
        msg = await _send_ai_reply(session, conversation=conversation, response=response)
    except WhatsAppNotConnected:
        logger.info("ai_handler: WA not connected, skipping reply")
        return None
    except Exception:
        logger.exception("ai_handler: send failed")
        await _handover_to_human(
            session,
            conversation=conversation,
            reason="send_failed",
        )
        return None

    return msg.id if msg is not None else None


__all__ = [
    "_matches_handover_keyword",
    "dispatch_ai_response",
]
