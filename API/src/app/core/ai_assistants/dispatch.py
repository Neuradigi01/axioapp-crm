"""Channel-agnostic AI-dispatch entry point
(``tasks/ai-assistants-omnichannel`` Step 5).

Every inbound channel routes through one function per channel here
so the "should AI answer?" decision lives in exactly one place:

  * Is a bound assistant configured for this org + channel?
  * Is the conversation currently paused (a human took over)?
  * Did the customer's message contain a handover keyword?

Only when ALL three gates pass do we delegate to the channel-specific
reply pipeline. This preserves the existing WhatsApp reply behaviour
while introducing the ``bound_channels`` + ``ai_paused`` guards that
Steps 1-4 built the state for.

Widget path (public embed) is unchanged in Step 5 — it already runs
through :class:`~core.ai_assistants.runtime.ChatRuntime` end-to-end
with its own session semantics; unifying it here is a follow-up
(refactor ``ChatRuntime`` to accept a ``ChannelContext``).

Email inbound is stubbed here for Step 5 and picked up in Step 6
(reply-worthiness guardrails must land before we auto-answer any
email — otherwise the assistant tries to reply to Amazon shipping
notifications).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants import email_guardrails, handover
from src.app.core.ai_assistants.models import AiAssistantChannel
from src.app.core.conversations.models import Conversation

logger = logging.getLogger(__name__)


async def route_whatsapp_inbound(
    session: AsyncSession,
    *,
    conversation: Conversation,
    inbound_text: str | None,
) -> None:
    """Called from ``conversations/service.py::receive_webhook`` for
    every inbound WhatsApp message. Never raises into the caller —
    AI failures must not surface as webhook 5xx (Meta would retry).

    Gate order:

      1. ``conversation.ai_paused=true`` → return silently. Human is
         already handling the thread; do not send an AI reply.
      2. Handover keyword match on the inbound text → auto-pause the
         conversation + return silently. The system marker message
         records the reason.
      3. Assistant bound to the ``whatsapp`` channel for this org →
         (currently) delegate to the legacy
         ``integrations.whatsapp.ai_handler.dispatch_ai_response``
         which handles LLM invocation + reply send. Step 5b will
         replace this with the unified ``ChatRuntime`` path.
      4. No bound assistant BUT the org still has the legacy
         ``ai_handling=true`` flag on the conversation → fall through
         to the legacy path for backward-compat until the flag is
         retired in a future track.
      5. Otherwise → silent skip. Human-only conversation.
    """
    # Refresh: caller may not have re-read after the inbound INSERT.
    await session.refresh(conversation)

    if conversation.ai_paused:
        return

    if handover.matches(inbound_text):
        try:
            from src.app.core.conversations.service import apply_auto_pause

            await apply_auto_pause(
                session,
                conversation=conversation,
                actor_user_id=None,
                reason="handover_keyword",
            )
            await session.commit()
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "ai_dispatch.handover_pause failed conv=%s",
                conversation.id,
            )
        return

    bound = await _da.find_active_assistant_bound_to_channel(
        session,
        channel=AiAssistantChannel.whatsapp.value,
    )

    if bound is None and not conversation.ai_handling:
        # Neither the new-style binding nor the legacy per-conversation
        # flag is set — this is a human-only conversation for this org.
        return

    # Delegate to the existing WhatsApp AI handler. It internally
    # loads org-level config, handles low-confidence escalation, and
    # sends the reply via the WhatsApp adapter. Step 5b replaces this
    # with a unified ChatRuntime call once the runtime accepts a
    # ``ChannelContext`` (deferred to keep Step 5's diff reviewable).
    try:
        from src.app.core.integrations.whatsapp.ai_handler import (
            dispatch_ai_response,
        )

        await dispatch_ai_response(
            session,
            conversation=conversation,
            inbound_text=inbound_text,
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception(
            "ai_dispatch.whatsapp delegate failed conv=%s",
            conversation.id,
        )


async def route_email_inbound(
    session: AsyncSession,
    *,
    conversation: Conversation,
    inbound_email: email_guardrails.InboundEmail | None = None,
    inbound_text: str | None = None,  # noqa: ARG001 — legacy signature; kept for API stability
) -> None:
    """Email counterpart to :func:`route_whatsapp_inbound`. Runs the
    reply-worthiness guardrail (:mod:`~core.ai_assistants.email_guardrails`)
    before ever considering an AI reply, so newsletters / bounces /
    role-account mail never trigger the LLM.

    Behaviour gate:

      * ``config.AI_EMAIL_INBOUND_ENABLED`` false (default) → silent
        return. Orgs upgrading without a bound email assistant see zero
        behaviour change until ops flip the flag.
      * ``conversation.ai_paused`` → silent return (human owns thread).
      * Guardrail rejects → structured log line records the reason for
        post-hoc analytics; no reply fires.
      * Guardrail passes → currently logs "would-reply" pending the
        ChannelContext outbound path (deferred alongside the
        ``ChatRuntime`` refactor). Once wired, the same delegate hook
        used by :func:`route_whatsapp_inbound` will send the reply
        through the existing email outbound module using
        :func:`~core.ai_assistants.email_threading.build_reply_thread`
        for the ``In-Reply-To`` / ``Re:`` / quoted-body threading.

    The ``inbound_email`` parameter is the guardrail input. Callers
    on the future email-sync path build it from the raw MIME envelope
    (``sender_email`` from ``From:``, ``headers`` from every mail
    header, ``body_text`` from the plain-text alternative). The old
    ``inbound_text``-only signature stays accepted for API stability
    but skips the guardrail (no headers ⇒ no way to filter role mail
    safely) — kept only so a caller that already exists doesn't crash
    when the flag flips on before it's updated.
    """
    from config import AI_EMAIL_INBOUND_ENABLED

    if not AI_EMAIL_INBOUND_ENABLED:
        return None

    await session.refresh(conversation)
    if conversation.ai_paused:
        return None

    if inbound_email is None:
        # Legacy call site — no envelope, no guardrail possible. Refuse
        # to auto-reply from an under-informed context (fail-closed).
        logger.info(
            "ai_dispatch.email skipped conv=%s reason=no_envelope",
            conversation.id,
        )
        return None

    ok, skip_reason = email_guardrails.is_reply_worthy(inbound_email)
    if not ok:
        logger.info(
            "ai_dispatch.email skipped conv=%s reason=%s sender=%s",
            conversation.id,
            skip_reason,
            inbound_email.sender_email,
        )
        return None

    # Email outbound send path lands in a follow-up step (needs the
    # ChannelContext refactor of ``ChatRuntime``). Log a hint so ops
    # can confirm the guardrail is picking real conversations before
    # the reply pipeline is turned on.
    logger.info(
        "ai_dispatch.email guardrail_pass conv=%s sender=%s subject=%r",
        conversation.id,
        inbound_email.sender_email,
        inbound_email.subject,
    )
    return None


__all__ = ["route_email_inbound", "route_whatsapp_inbound"]
