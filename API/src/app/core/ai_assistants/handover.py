"""Handover-keyword detection for AI conversations
(``tasks/ai-assistants-omnichannel`` Step 5).

Every channel that runs an AI reply pipeline (widget, WhatsApp, email,
and future Instagram/Messenger) checks the customer's inbound text
against this list BEFORE calling the LLM. A match short-circuits the
LLM roundtrip, auto-pauses the conversation, and appends a system
marker message so the transcript records why AI stepped back.

Extracted from ``core/integrations/whatsapp/ai_handler.py`` so the
same keyword semantics apply on every channel — before Step 5 the
detection was WhatsApp-only.

The default keyword list is intentionally small and Anglosphere-neutral
(no idioms, no punctuation). Orgs can extend it via their existing
``AiSettings.ai_handover_keywords`` list — the ``matches`` helper
merges the operator additions with the defaults.
"""

from __future__ import annotations

from collections.abc import Iterable

# Base list — short, unambiguous, works out of the box for any org
# that hasn't customised keywords. Case-insensitive substring match,
# so ``"Please, can I talk to a human being?"`` matches
# ``"talk to a human"``.
DEFAULT_HANDOVER_KEYWORDS: frozenset[str] = frozenset(
    {
        "talk to human",
        "talk to a human",
        "human please",
        "real person",
        "agent please",
        "speak to agent",
        "speak to a person",
        "stop bot",
        "not a bot",
    }
)


def matches(text: str | None, *, extra_keywords: Iterable[str] | None = None) -> bool:
    """True iff ``text`` contains any keyword from the default list OR
    the operator-supplied ``extra_keywords``. Case-insensitive substring
    match. Empty / None text → False. Blank keyword strings are
    ignored (guards against a stray empty entry in
    ``ai_handover_keywords``)."""
    if not text:
        return False
    lowered = text.lower()
    combined: list[str] = [k for k in DEFAULT_HANDOVER_KEYWORDS if k]
    if extra_keywords:
        combined.extend(k for k in extra_keywords if k)
    return any(kw.lower() in lowered for kw in combined)


__all__ = ["DEFAULT_HANDOVER_KEYWORDS", "matches"]
