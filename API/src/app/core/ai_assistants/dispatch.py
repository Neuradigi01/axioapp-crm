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

    logger.warning(
        "ai_dispatch.whatsapp entered conv=%s org=%s paused=%s handling=%s",
        conversation.id,
        conversation.org_id,
        conversation.ai_paused,
        conversation.ai_handling,
    )

    if conversation.ai_paused:
        logger.warning("ai_dispatch.whatsapp skipped conv=%s reason=paused", conversation.id)
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
    logger.warning(
        "ai_dispatch.whatsapp bound_assistant=%s",
        bound.id if bound is not None else None,
    )

    if bound is not None:
        # Step 5b — new-style BYOK path. The bound assistant's own
        # prompt / knowledge base / model choice answers the message,
        # via the shared ``ChatRuntime``. Legacy delegate only kicks
        # in when the org hasn't bound an assistant to WhatsApp yet.
        try:
            logger.warning(
                "ai_dispatch.whatsapp byok invoking conv=%s assistant=%s",
                conversation.id,
                bound.id,
            )
            await _run_byok_whatsapp_reply(
                session,
                conversation=conversation,
                assistant_id=bound.id,
                inbound_text=inbound_text or "",
            )
            logger.warning(
                "ai_dispatch.whatsapp byok completed conv=%s assistant=%s",
                conversation.id,
                bound.id,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "ai_dispatch.whatsapp byok failed conv=%s assistant=%s",
                conversation.id,
                bound.id,
            )
        return

    if not conversation.ai_handling:
        # Neither the new-style binding nor the legacy per-conversation
        # flag is set — this is a human-only conversation for this org.
        return

    # Legacy fallback — org still on the pre-omnichannel `ai_handling`
    # flag, no bound assistant. Delegates to the org-level generic
    # AI handler. Retire once every org migrates to a bound assistant.
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
            "ai_dispatch.whatsapp legacy delegate failed conv=%s",
            conversation.id,
        )


async def _run_byok_whatsapp_reply(
    session,  # AsyncSession — type import lives at module top
    *,
    conversation: Conversation,
    assistant_id,  # uuid.UUID
    inbound_text: str,
) -> None:
    """Run the BYOK ``ChatRuntime`` against the given assistant + the
    live WhatsApp conversation, drain the streamed reply, and send it
    via the existing WhatsApp adapter. Step 5b.

    Keeps the runtime's transport-agnostic contract: the runtime just
    yields token chunks; this function collects them and hands the
    full text to the WhatsApp adapter. Same pattern will apply to
    Email in a follow-up (email's outbound adapter takes a full body
    string, not a stream)."""
    from datetime import UTC, datetime

    from src.app.core.ai_assistants.runtime import ChatRuntime
    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppNotConnected,
        resolve_whatsapp_adapter,
    )
    from src.app.core.conversations.models import (
        Message,
        MessageDirection,
    )

    runtime = ChatRuntime(
        db=session,
        org_id=conversation.org_id,
        assistant_id=assistant_id,
        user_message=inbound_text,
        session_token=f"wa:{conversation.id}",
        is_public=True,
        existing_conversation_id=conversation.id,
    )

    full_reply: list[str] = []
    async for chunk in runtime.stream_reply():
        if chunk.type == "token" and chunk.delta:
            full_reply.append(chunk.delta)
    text = "".join(full_reply).strip()
    if not text:
        # Runtime already persisted a fallback message + committed —
        # nothing left to send. Silent.
        return

    try:
        adapter = await resolve_whatsapp_adapter(session)
    except WhatsAppNotConnected:
        logger.info(
            "ai_dispatch.whatsapp byok skipped conv=%s reason=wa_not_connected",
            conversation.id,
        )
        return

    ref = await adapter.send(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        text=text,
        attachments=[],
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    outbound = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=text,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "author": "ai",
            "assistant_id": str(assistant_id),
            "adapter_ref": ref.channel_message_id,
            "source": "byok_whatsapp",
        },
        sent_at=sent_at,
    )
    session.add(outbound)
    conversation.last_message_at = sent_at
    await session.commit()

    # Push a WS event so any assignee currently viewing the thread sees
    # the AI's reply live — without this, the operator has to switch
    # tabs (which force-reloads the detail) before the outbound bubble
    # appears. Same shape as ``conversations/service.py::receive_webhook``
    # uses for inbound events so the frontend's ``onIncomingNotification``
    # matches on ``payload.conversation_id`` uniformly. Best-effort:
    # ``notify`` never raises, and no assignee → skip silently (the
    # conversation is still human-unowned; no one to push to).
    if conversation.assigned_to_id is not None:
        from src.app.core.notifications.service import notify

        await notify(
            org_id=conversation.org_id,
            user_id=conversation.assigned_to_id,
            type="conversation.message",
            title=f"AI replied on {conversation.channel.value}",
            body=text[:160] or None,
            payload={
                "conversation_id": str(conversation.id),
                "channel": conversation.channel.value,
                "author": "ai",
            },
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
