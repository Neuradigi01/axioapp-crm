"""Assign AI Assistant node
(``tasks/chatbot-builder`` Step 10, wired live in
``tasks/ai-assistants`` Step 9).

Hand the conversation over to an ongoing AI Assistant. Every
subsequent inbound message on the parent conversation is answered
by the same assistant until ``max_turns`` is reached, at which
point the bot flow advances via the ``handed_off`` port to the
next node (typically ``End Bot`` or a follow-up scripted step).
Human takeover also ends the loop — the engine already cancels
parked bot runs when ``pause_ai`` / ``apply_auto_pause`` fires in
``conversations/service.py``.

Execution flow:

  * **Fresh call** (no ``ai_assistant_id`` in ``run.context``) —
    pick the assistant, seed context (id + turn counter), run one
    AI turn against the latest inbound text if any, then park
    waiting for the next inbound. Running-on-first-pass matters
    because the customer's message that triggered the flow into
    this node has already been consumed by the engine — we want
    the AI to reply to it immediately, not silently wait for a
    second message.

  * **Resume from inbound** (assistant already assigned) — call
    :func:`core.ai_assistants.runtime.reply_once` on
    ``run.context['last_inbound_text']``, dispatch the reply via
    the WhatsApp adapter, decrement ``ai_assistant_turns_remaining``,
    park again for the next inbound (or advance via ``handed_off``
    when turns are exhausted).

Config shape (accepted at save-time)::

    {
      "assistant_id": "<optional AI assistant uuid>",
      "max_turns": 8
    }

``assistant_id`` blank → the org's first ACTIVE assistant so
simple flows work out of the box.

Output ports:
  * ``handed_off`` — max_turns reached; flow advances.
  * ``error``      — no assistant available / bad UUID / AI runtime
                     failure. Advance to a fallback branch (e.g.
                     "Sorry, I couldn't reach the AI").

Reply-send parity: uses the same pattern as
``ai_assistants/dispatch::_run_byok_whatsapp_reply`` — resolve the
WhatsApp adapter, ``adapter.send()``, persist an ``out`` ``Message``
row with ``payload.author='ai'`` + ``source='chatbot_ai_assistant_node'``,
and push a ``notify()`` event so any operator watching the inbox
sees the reply live.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.ai_assistants.runtime import reply_once
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "assign_ai_assistant"
# Default is 0 = "unlimited turns" — once the bot hands over to the
# AI, the AI keeps answering every subsequent inbound until a human
# takes over (which cancels the parked run via
# ``cancel_parked_runs_for_conversation``). Operators can set an
# explicit positive N to force the flow back to scripted mode after
# N customer messages.
_DEFAULT_MAX_TURNS = 0


async def _pick_assistant_id(
    session,
    *,
    org_id: uuid.UUID,
    configured_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if configured_id is not None:
        return configured_id
    stmt = (
        select(AiAssistant.id)
        .where(
            AiAssistant.org_id == org_id,
            AiAssistant.status == AiAssistantStatus.active,
        )
        .order_by(AiAssistant.created_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _run_ai_turn_and_send(
    session,
    *,
    conversation,
    assistant_id: uuid.UUID,
    user_text: str,
) -> str | None:
    """One end-to-end AI turn on the parent conversation:

      1. Call ``reply_once`` (streaming runtime, drained to string).
      2. Send the reply via the WhatsApp adapter — returns None if
         WhatsApp isn't connected on this org (silent skip, next
         inbound will retry).
      3. Persist an ``out`` ``Message`` row so the reply shows up in
         the inbox / thread + counts against retention.
      4. Push a WS ``notify`` so the operator's open thread refreshes
         live without a tab switch — mirrors the fix on
         ``dispatch::_run_byok_whatsapp_reply``.

    Returns the reply text on success, ``None`` when nothing was
    sent (empty reply / no adapter). Never raises into the caller —
    handler catches upstream so the bot flow doesn't die on a
    transient OpenAI outage.
    """
    from src.app.core.conversations.adapters.whatsapp import (
        WhatsAppNotConnected,
        resolve_whatsapp_adapter,
    )
    from src.app.core.conversations.models import Message, MessageDirection
    from src.app.core.notifications.service import notify

    reply_text = await reply_once(
        db=session,
        org_id=conversation.org_id,
        assistant_id=assistant_id,
        user_message=user_text or "",
        session_token=f"bot_ai:{conversation.id}",
        is_public=False,
    )
    if not reply_text:
        return None

    try:
        adapter = await resolve_whatsapp_adapter(session)
    except WhatsAppNotConnected:
        return None

    ref = await adapter.send(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        text=reply_text,
        attachments=[],
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    outbound = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=reply_text,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "author": "ai",
            "assistant_id": str(assistant_id),
            "adapter_ref": ref.channel_message_id,
            "source": "chatbot_ai_assistant_node",
        },
        sent_at=sent_at,
    )
    session.add(outbound)
    conversation.last_message_at = sent_at
    await session.commit()

    if conversation.assigned_to_id is not None:
        await notify(
            org_id=conversation.org_id,
            user_id=conversation.assigned_to_id,
            type="conversation.message",
            title=f"AI replied on {conversation.channel.value}",
            body=reply_text[:160] or None,
            payload={
                "conversation_id": str(conversation.id),
                "channel": conversation.channel.value,
                "author": "ai",
            },
        )
    return reply_text


def _park_or_exit(
    *,
    max_turns: int,
    turns_left: int,
    conversation_id,
    context_patch: dict,
) -> NodeResult:
    """Turn accounting: park for the next inbound while turns remain,
    otherwise fire the ``handed_off`` port so the flow advances.

    ``max_turns == 0`` is the "unlimited" convention — the node just
    parks forever (until a human takes over, which cancels the parked
    run). We still track ``turns_remaining`` in context for observability
    even in unlimited mode; the exit check just never triggers."""
    unlimited = max_turns <= 0
    if not unlimited and turns_left <= 0:
        return NodeResult(
            next_edge_label="handed_off",
            context_patch={
                **context_patch,
                "ai_assistant_id": None,
                "ai_assistant_turns_remaining": 0,
            },
            output={"reason": "max_turns_exhausted"},
        )
    conv_id = str(conversation_id) if conversation_id else "test"
    return NodeResult(
        park_key=("reply", conv_id),
        context_patch={
            **context_patch,
            "ai_assistant_turns_remaining": turns_left,
        },
        output={
            "turns_remaining": turns_left,
            "unlimited": unlimited,
        },
    )


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    ctx_data = ctx.run_context or {}
    is_resume = _shared.is_resumed_from_park(ctx)

    # --- Resume path: assistant already assigned, run one AI turn. ---
    if is_resume and ctx_data.get("ai_assistant_id"):
        assistant_id_raw = ctx_data["ai_assistant_id"]
        try:
            assistant_id = uuid.UUID(str(assistant_id_raw))
        except ValueError:
            return NodeResult(
                next_edge_label="error",
                context_patch={
                    **_shared.clear_resume_flag(),
                    "ai_assistant_id": None,
                },
                output={"reason": f"bad ai_assistant_id in ctx: {assistant_id_raw!r}"},
            )

        max_turns = int(ctx_data.get("ai_assistant_max_turns", _DEFAULT_MAX_TURNS))
        turns_left = int(ctx_data.get("ai_assistant_turns_remaining", 0))
        user_text = str(ctx_data.get("last_inbound_text") or "")

        if not ctx.is_test:
            conversation = await _shared.load_conversation(
                ctx.session, conversation_id=ctx.run.conversation_id
            )
            if conversation is not None:
                try:
                    await _run_ai_turn_and_send(
                        ctx.session,
                        conversation=conversation,
                        assistant_id=assistant_id,
                        user_text=user_text,
                    )
                except Exception as exc:  # noqa: BLE001
                    return NodeResult(
                        next_edge_label="error",
                        context_patch={
                            **_shared.clear_resume_flag(),
                            "ai_assistant_id": None,
                        },
                        output={"reason": f"ai_runtime_error: {exc}"},
                    )

        # Only decrement in "limited turns" mode. In unlimited mode we
        # leave the counter alone so the observability output stays
        # meaningful (it just reads as "still 0 remaining, unlimited").
        next_turns_left = turns_left if max_turns <= 0 else turns_left - 1
        return _park_or_exit(
            max_turns=max_turns,
            turns_left=next_turns_left,
            conversation_id=ctx.run.conversation_id,
            context_patch=_shared.clear_resume_flag(),
        )

    # --- Fresh call: pick assistant + do the first turn if we have
    #     something to reply to, then park.
    configured_raw = cfg.get("assistant_id")
    configured_id: uuid.UUID | None = None
    if configured_raw:
        try:
            configured_id = uuid.UUID(str(configured_raw))
        except ValueError:
            return NodeResult(
                next_edge_label="error",
                skip_reason="bad_assistant_id",
                output={"reason": f"invalid assistant_id: {configured_raw!r}"},
            )

    assistant_id: uuid.UUID | None = None
    if ctx.session is not None:
        assistant_id = await _pick_assistant_id(
            ctx.session,
            org_id=ctx.run.org_id,
            configured_id=configured_id,
        )
    if assistant_id is None:
        return NodeResult(
            next_edge_label="error",
            skip_reason="no_ai_assistant_available",
            output={
                "reason": (
                    "No active AI assistant found for this org. Create one at "
                    "/user/ai-assistants and set it to Active, or set "
                    "config.assistant_id explicitly."
                ),
            },
        )

    # ``max_turns`` clamps to non-negative — negatives coerce to 0 =
    # unlimited so bad config never silently exits the flow after one
    # turn. ``max_turns > 0`` means "N-turn cap"; ``max_turns == 0``
    # means "unlimited (until human takeover)".
    max_turns = max(0, int(cfg.get("max_turns", _DEFAULT_MAX_TURNS)))
    turns_left = max_turns
    context_patch: dict = {
        "ai_assistant_id": str(assistant_id),
        "ai_assistant_max_turns": max_turns,
    }

    # If the customer message that walked the flow into this node
    # is available, reply to it right now — skipping this would
    # leave the customer waiting on a second nudge before the AI
    # says anything.
    user_text = str(ctx_data.get("last_inbound_text") or "")
    if user_text and not ctx.is_test:
        conversation = await _shared.load_conversation(
            ctx.session, conversation_id=ctx.run.conversation_id
        )
        if conversation is not None:
            try:
                await _run_ai_turn_and_send(
                    ctx.session,
                    conversation=conversation,
                    assistant_id=assistant_id,
                    user_text=user_text,
                )
                # Only decrement in "limited turns" mode.
                if max_turns > 0:
                    turns_left = max_turns - 1
            except Exception as exc:  # noqa: BLE001
                return NodeResult(
                    next_edge_label="error",
                    context_patch={**context_patch, "ai_assistant_id": None},
                    output={"reason": f"ai_runtime_error: {exc}"},
                )

    return _park_or_exit(
        max_turns=max_turns,
        turns_left=turns_left,
        conversation_id=ctx.run.conversation_id,
        context_patch=context_patch,
    )


register_node(_NODE_TYPE, handle)
