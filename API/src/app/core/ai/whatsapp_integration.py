"""AI ↔ WhatsApp glue (whatsapp-platform-upgrade Step 19).

Single public entry point — :func:`generate_response` — that takes a
conversation snapshot + the latest inbound message and returns an
:class:`AIResponse` with the reply text, confidence, and optional
handover signal.

The LLM call lives inside ``_invoke_llm`` — a clearly-marked
extension point. Today it's a deterministic heuristic stub so the
WhatsApp pipeline can ship without a paid API key; tomorrow swap
``_invoke_llm`` to call Anthropic / OpenAI / Gemini / a self-hosted
model.

Why a stub?
  * The rest of Step 19 (handover logic, conversation toggle, audit,
    bubble badge) is real production code. Wiring an actual LLM
    requires choosing a vendor + paying for tokens — orthogonal to
    the plumbing.
  * The stub returns a plausible-shaped response (text + confidence)
    so integration tests + smoke flow work end-to-end.
  * The confidence varies with input shape: short questions get
    high confidence ("hours", "price"), long / ambiguous get low —
    enough variation to exercise the handover threshold.

Replace ``_invoke_llm`` with a real call and the rest of the
pipeline picks it up unchanged.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One inbound or outbound message in the rolling context the LLM
    sees. Kept minimal — just role + text. Channel metadata + reactions
    are stripped (not useful for the model)."""

    role: str  # "user" (the customer) | "assistant" (operator/AI) | "system"
    text: str


@dataclass(frozen=True, slots=True)
class AIResponse:
    """LLM result. ``confidence`` is 0.0..1.0; the handler compares
    against the org's ``ai_confidence_threshold`` to decide whether to
    send the response or escalate to a human."""

    text: str
    confidence: float
    handover_requested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# --- public entry point ----------------------------------------------------


_DEFAULT_SYSTEM_PROMPT = (
    "You are a polite, concise WhatsApp customer-service assistant. "
    "Reply in the customer's language. Do NOT commit to specific "
    "prices, availability, dates, or warranties — defer those to a "
    "human teammate. If unsure or the customer asks for a human, "
    "request handover. Keep replies under 200 characters when "
    "possible. Never invent facts about the business."
)


async def generate_response(
    *,
    system_prompt: Optional[str],
    history: list[ConversationTurn],
    latest_inbound_text: str,
) -> AIResponse:
    """Produce an AI reply for the WhatsApp handler to send.

    `history` is most-recent-last; the caller passes the trimmed
    transcript (typically last 20 turns) — token-budget control
    lives in the caller so this module stays vendor-agnostic.

    Failures inside the LLM call are caught + surfaced as a
    low-confidence response with a clear text body. The handler
    treats low confidence as "escalate to human" so a flaky LLM
    never strands the customer."""
    composed_prompt = (system_prompt or "").strip() or _DEFAULT_SYSTEM_PROMPT
    try:
        return await _invoke_llm(
            system_prompt=composed_prompt,
            history=history,
            latest_inbound_text=latest_inbound_text,
        )
    except Exception:
        logger.exception("AI invocation failed; returning low-confidence stub")
        return AIResponse(
            text=(
                "Hi! I'm having trouble responding right now — let me "
                "get a teammate to help."
            ),
            confidence=0.0,
            handover_requested=True,
            metadata={"error": "invocation_failed"},
        )


# --- extension point -------------------------------------------------------


_HOURS_RE = re.compile(r"\b(hours|open|timing|when.*open)\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"\b(price|cost|rate|charge|fee|how much)\b", re.IGNORECASE)
_GREETING_RE = re.compile(
    r"^(hi|hello|hey|namaste|hola|good (morning|afternoon|evening))",
    re.IGNORECASE,
)


async def _invoke_llm(
    *,
    system_prompt: str,
    history: list[ConversationTurn],
    latest_inbound_text: str,
) -> AIResponse:
    """The single function to swap when wiring a real LLM.

    Today: a deterministic heuristic that produces plausibly-shaped
    responses so the rest of the Step-19 pipeline (handover, audit,
    bubble badge) can be tested end-to-end without an LLM bill.

    To wire a real LLM (Anthropic / OpenAI / Gemini / Bedrock / a
    self-hosted model) — replace this function body with:

      1. Build the provider's messages array from `history` +
         `latest_inbound_text` + `system_prompt`.
      2. Call the SDK with a reasonable max_tokens (~300).
      3. Parse the response + map the provider's logprobs / heuristic
         self-rating onto our 0.0..1.0 confidence scale.
      4. Detect handover phrasing in the response itself
         (provider-specific structured output is cleaner if available).
      5. Return ``AIResponse(text, confidence, handover_requested)``.

    Provider-specific concerns (rate-limit, token budget, streaming,
    retry-on-5xx) all belong inside this function — the caller stays
    vendor-agnostic.
    """
    text = (latest_inbound_text or "").strip()
    lowered = text.lower()

    # Operator handover phrasing detected — let the handler escalate.
    if any(
        phrase in lowered
        for phrase in (
            "i don't know",
            "i'm not sure",
            "complicated",
            "speak to a manager",
        )
    ):
        return AIResponse(
            text="Let me get a human teammate to help with this.",
            confidence=0.3,
            handover_requested=True,
        )

    if _HOURS_RE.search(text):
        return AIResponse(
            text=(
                "Our business hours are listed on our WhatsApp profile — "
                "you can see them by tapping the business name at the "
                "top of this chat. How else can I help?"
            ),
            confidence=0.85,
        )

    if _PRICE_RE.search(text):
        # Per the system prompt we don't commit to prices — defer to
        # human with low-medium confidence so the handler escalates
        # under most thresholds.
        return AIResponse(
            text=(
                "Pricing varies by product — let me connect you with "
                "a teammate who can quote accurately."
            ),
            confidence=0.5,
            handover_requested=True,
        )

    if _GREETING_RE.search(text):
        return AIResponse(
            text="Hi! How can I help you today?",
            confidence=0.9,
        )

    # Catch-all: confidence proportional to message length (short
    # messages are easier to answer than long rambles). Caller uses
    # this against the org threshold to decide handover.
    word_count = len(text.split())
    if word_count == 0:
        confidence = 0.0
    elif word_count <= 6:
        confidence = 0.7
    elif word_count <= 20:
        confidence = 0.55
    else:
        confidence = 0.35

    return AIResponse(
        text=(
            "Thanks for your message — I'm processing it and a "
            "teammate will follow up shortly."
        ),
        confidence=confidence,
        handover_requested=confidence < 0.4,
    )


# --- helpers for the handler -----------------------------------------------


def history_from_messages(
    messages: Iterable[Any],
    *,
    max_turns: int = 20,
) -> list[ConversationTurn]:
    """Project ``Message`` rows into the LLM-facing turn list.

    Newest turn is last; ``max_turns`` caps the rolling window so a
    long-running conversation doesn't blow the prompt budget. Skips
    internal notes (Step 13) — those are operator-only and never
    appear in the LLM context."""
    rows = list(messages)
    # Most-recent-last is what we want, so don't reverse — but cap.
    if len(rows) > max_turns:
        rows = rows[-max_turns:]
    out: list[ConversationTurn] = []
    for m in rows:
        if getattr(m, "is_internal", False):
            continue
        role = (
            "user"
            if getattr(m, "direction", "out") == "in"
            else "assistant"
        )
        text = getattr(m, "text", None)
        if text:
            out.append(ConversationTurn(role=role, text=text))
    return out


__all__ = [
    "AIResponse",
    "ConversationTurn",
    "generate_response",
    "history_from_messages",
]
