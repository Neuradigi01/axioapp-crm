"""Agent-side AI help: suggest a reply, summarise a thread.

Uses the org's own AI Assistant setup — the assistant bound to the
channel (else any active assistant) supplies the provider key + model,
and every call goes through the org AI budget (pre-flight cap check,
then the real cost is charged). Nothing is sent to the customer: the
suggestion lands in the operator's composer.

:func:`complete_with_org_assistant` is the shared entry point other
modules (e.g. Reviews' suggested reply) call so they reuse the same
key, budget and error handling.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import data_access as _ai_da
from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.conversations.models import Message, MessageDirection
from src.app.core.conversations.service import get_conversation, list_messages
from src.app.core.integrations.ai import service as _budget_service
from src.app.shared.llm import ProviderError, factory
from src.app.shared.llm.pricing import cost_for

logger = logging.getLogger(__name__)

# Recent messages fed to the model — enough context for a reply or a
# summary while keeping the prompt (and the bill) small.
_CONTEXT_MESSAGES = 30
_MAX_CHARS_PER_MESSAGE = 1200

_SUGGEST_SYSTEM = (
    "You draft replies for a customer-support agent. Write the agent's next "
    "message to the customer: friendly, concise, in the customer's language. "
    "Do not invent prices, stock, dates or policies that are not in the "
    "conversation — if something must be confirmed, say the agent will check. "
    "Return only the message text, no preamble."
)
_SUMMARY_SYSTEM = (
    "You summarise customer conversations for support agents. Give a short "
    "summary (3-6 bullet points): what the customer wants, what has been "
    "answered or promised, and any open question or next step. Plain text "
    "bullets starting with '- '. No preamble."
)

AssistMode = Literal["suggest_reply", "summarize"]


async def _resolve_assistant(session: AsyncSession, channel: str | None) -> AiAssistant:
    assistant = (
        await _ai_da.find_active_assistant_bound_to_channel(session, channel=channel)
        if channel
        else None
    )
    if assistant is None:
        active = await _ai_da.list_assistants(
            session, filter_status=AiAssistantStatus.active, limit=1
        )
        assistant = active[0] if active else None
    if assistant is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set up an active AI Assistant (Settings → AI Assistants) to use AI help.",
        )
    return assistant


def _transcript(messages: list[Message], *, include_notes: bool) -> str:
    lines: list[str] = []
    for m in messages:
        text = (m.text or "").strip()
        if not text:
            continue
        if m.is_internal:
            if not include_notes:
                continue
            speaker = "Internal note"
        elif m.direction == MessageDirection.in_:
            speaker = "Customer"
        else:
            speaker = "AI" if m.payload and m.payload.get("author") == "ai" else "Agent"
        lines.append(f"{speaker}: {text[:_MAX_CHARS_PER_MESSAGE]}")
    return "\n".join(lines)


async def complete_with_org_assistant(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: str | None,
    system: str,
    user_prompt: str,
    max_tokens: int,
    include_business_context: bool = False,
) -> str:
    """One budget-checked completion with the org's AI Assistant (bound
    to ``channel`` when given, else any active one). Raises 409 when no
    assistant is set up, 429 when the AI budget is spent, 502 when the
    provider fails or answers empty. ``include_business_context``
    appends the assistant's own instructions to ``system``."""
    assistant = await _resolve_assistant(session, channel)

    allowed, reason = await _budget_service.charge_budget(
        session, org_id=org_id, cost_usd=Decimal("0"), dry_run=True
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "The AI budget for this organisation is used up "
                f"({(reason or 'cap reached').replace('_', ' ')})."
            ),
        )

    if include_business_context and assistant.instructions:
        system += "\n\nBusiness context from the org's assistant:\n" + assistant.instructions

    llm = factory("openai", db=session, org_id=org_id, key_id=assistant.key_id)
    try:
        response = await llm.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            model=assistant.model,
            temperature=0.4,
            max_tokens=max_tokens,
        )
    except ProviderError as exc:
        logger.warning("ai_assist provider error org=%s: %s", org_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI provider could not answer right now. Try again in a moment.",
        ) from exc

    try:
        cost = cost_for(response.usage, assistant.model)
    except KeyError:
        logger.warning("ai_assist no price for model=%s", assistant.model)
        cost = Decimal("0")
    await _budget_service.charge_budget(session, org_id=org_id, cost_usd=cost, dry_run=False)

    text = (response.content or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI returned an empty answer. Try again.",
        )
    return text


async def run_ai_assist(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    org_id: uuid.UUID,
    mode: AssistMode,
) -> str:
    """Return a suggested reply or a thread summary for the operator."""
    conversation = await get_conversation(session, conversation_id)
    messages = await list_messages(session, conversation_id, limit=_CONTEXT_MESSAGES)
    transcript = _transcript(messages, include_notes=mode == "summarize")
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="There are no messages to work with yet.",
        )

    if mode == "suggest_reply":
        return await complete_with_org_assistant(
            session,
            org_id=org_id,
            channel=conversation.channel.value,
            system=_SUGGEST_SYSTEM,
            user_prompt=f"Conversation so far:\n{transcript}\n\nWrite the agent's next reply.",
            max_tokens=400,
            include_business_context=True,
        )
    return await complete_with_org_assistant(
        session,
        org_id=org_id,
        channel=conversation.channel.value,
        system=_SUMMARY_SYSTEM,
        user_prompt=f"Conversation:\n{transcript}",
        max_tokens=500,
    )
