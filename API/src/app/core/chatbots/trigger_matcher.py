"""Chatbot trigger matcher (``tasks/chatbot-builder`` Step 5).

Subscribes to :data:`core.events.event_catalog.WHATSAPP_MESSAGE_RECEIVED`
and :data:`core.events.event_catalog.EMAIL_MESSAGE_RECEIVED` and turns
inbound-message events into bot-run starts.

Gates applied in order:

  1. **Opt-out** — reuses :mod:`core.workflows.compliance` to check
     marketing consent + block list. Opted-out contacts are silently
     skipped (Decision §11).
  2. **Channel filter** — bots whose ``trigger_config.channel`` is
     ``any`` or matches the inbound channel are eligible.
  3. **Trigger match** — keyword (word-boundary case-insensitive by
     default) OR regex (via ``google-re2`` if installed, else Python
     ``re`` with a save-time complexity linter + 4KB text cap).
  4. **First-message-only** — if the bot's trigger has this flag,
     only fires when the payload's ``is_first_message=True``.
  5. **Priority resolution** — matches are already sorted by
     ``priority DESC, created_at ASC`` at the DAL layer; first match
     wins. Losers get a ``skipped_by_priority`` diagnostic row.
  6. **Idempotency** — before starting the run, check
     :func:`has_active_run_for_bot_conversation`. If an active run
     exists, this inbound is destined for the parked-wait resume
     path (Step 6 wires that); the matcher records
     ``active_run_exists`` and stops.

Public entry points:

  * :func:`has_any_matching_bot` — cheap sync pre-check used by
    :func:`conversations.service.receive_webhook` for the precedence
    rule (Decision §12). No opt-out gate here — the pre-check answers
    "would ANY bot match" for the inline-skip decision, which is
    independent of the specific contact's consent state (a bot that
    would match a compliant contact still exists).

  * :func:`on_inbound` — the bus subscriber. Registered on module
    import via :func:`register_bus_subscribers`.
"""

from __future__ import annotations

import functools
import logging
import re as _stdlib_re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import data_access as _dal
from src.app.core.chatbots import engine as _engine
from src.app.core.chatbots.models import Chatbot
from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import (
    EMAIL_MESSAGE_RECEIVED,
    WHATSAPP_MESSAGE_RECEIVED,
)
from src.app.core.workflows import compliance as wf_compliance

logger = logging.getLogger(__name__)


# --- Regex engine choice --------------------------------------------------

try:
    import re2 as _re_engine  # type: ignore[import-not-found]

    _RE2_AVAILABLE = True
except ImportError:  # pragma: no cover — Windows dev fallback
    _re_engine = _stdlib_re  # type: ignore[assignment]
    _RE2_AVAILABLE = False


# Text-length cap — Case #19: 10 KB inbounds are turned into 4 KB
# match windows so pathological patterns can't sit on a CPU. Storage
# of the full text is unaffected.
_MAX_MATCH_TEXT_BYTES = 4 * 1024

# Save-time linter — reject patterns with the classic
# nested-quantifier ReDoS shapes when we're on the Python `re`
# fallback path. Nested quantifier prefixes almost always indicate a
# pattern that will backtrack catastrophically on a hostile input.
_DANGEROUS_PATTERN_SHAPES = (
    _stdlib_re.compile(r"\([^)]*[+*]\)[+*]"),  # (x+)+  (x*)*  (x+)*
    _stdlib_re.compile(r"\([^)]+\|[^)]+\)[+*]"),  # (a|b|c)+ with overlapping alts
)


class UnsafeRegex(ValueError):
    """Raised at save-time when the pattern would ReDoS on the
    Python-``re`` fallback path. Router turns this into 422."""


def lint_regex_pattern(pattern: str) -> None:
    """Reject known-catastrophic patterns when re2 isn't available.

    Belt to the 500-char cap from :class:`TriggerConfig` — the cap
    keeps runtime bounded, this linter keeps the pattern from
    exploiting the bound. Called by :mod:`core.chatbots.service` on
    every save when the trigger mode is ``regex``.
    """
    if _RE2_AVAILABLE:
        # re2 has no ReDoS surface — accept any pattern re2 will
        # compile. Compile-check here so we fail fast.
        try:
            _re_engine.compile(pattern)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001  (re2 error class varies)
            raise UnsafeRegex(f"regex failed to compile: {exc}") from exc
        return

    for shape in _DANGEROUS_PATTERN_SHAPES:
        if shape.search(pattern):
            raise UnsafeRegex(
                "regex contains a nested-quantifier shape that can ReDoS on "
                "this platform (google-re2 not installed). Simplify the "
                "pattern or install google-re2."
            )
    try:
        _stdlib_re.compile(pattern)
    except _stdlib_re.error as exc:
        raise UnsafeRegex(f"regex failed to compile: {exc}") from exc


@functools.lru_cache(maxsize=256)
def _compiled_regex(pattern: str, case_sensitive: bool):  # type: ignore[no-untyped-def]
    """LRU-cached compiled regex. Cache key does not include a
    version number because the cap on unique (pattern,
    case_sensitive) tuples is bounded — LRU eviction handles
    invalidation on bot save without needing an explicit bump."""
    flags = 0
    if not case_sensitive:
        flags |= _re_engine.IGNORECASE if _RE2_AVAILABLE else _stdlib_re.IGNORECASE
    return _re_engine.compile(pattern, flags)


# --- Match primitives -----------------------------------------------------


def _matches_keyword(text: str, keywords: list[str], case_sensitive: bool) -> bool:
    """Word-boundary substring match. Case-insensitive by default.
    All keywords are tested; first hit wins."""
    if not keywords or not text:
        return False
    haystack = text if case_sensitive else text.lower()
    for kw in keywords:
        needle = kw if case_sensitive else kw.lower()
        if not needle:
            continue
        # Word-boundary check without a regex round-trip. Cheaper on
        # short keywords and dodges the ReDoS surface entirely.
        idx = haystack.find(needle)
        while idx != -1:
            left_ok = idx == 0 or not haystack[idx - 1].isalnum()
            right_edge = idx + len(needle)
            right_ok = right_edge == len(haystack) or not haystack[right_edge].isalnum()
            if left_ok and right_ok:
                return True
            idx = haystack.find(needle, idx + 1)
    return False


def _matches_regex(text: str, pattern: str, case_sensitive: bool) -> bool:
    """Compile-cached regex search. Returns False on any compile /
    match error rather than propagating — a bad pattern shouldn't
    kill the whole matcher pass."""
    try:
        compiled = _compiled_regex(pattern, case_sensitive)
        return compiled.search(text) is not None
    except Exception:  # noqa: BLE001
        logger.exception(
            "chatbots.matcher.regex_error pattern=%s case_sensitive=%s",
            pattern[:80],
            case_sensitive,
        )
        return False


def _bot_matches(bot: Chatbot, text: str | None, is_first_message: bool) -> bool:
    """Evaluate one bot's trigger config against an inbound message."""
    cfg = bot.trigger_config or {}
    if cfg.get("first_message_only") and not is_first_message:
        return False

    mode = cfg.get("mode") or "any"
    if mode == "any":
        return True

    if text is None:
        return False
    truncated = text.encode("utf-8", errors="ignore")[:_MAX_MATCH_TEXT_BYTES].decode(
        "utf-8", errors="ignore"
    )

    case_sensitive = bool(cfg.get("case_sensitive"))
    if mode == "keyword":
        return _matches_keyword(truncated, cfg.get("keywords") or [], case_sensitive)
    if mode == "regex":
        pattern = cfg.get("regex_pattern")
        if not pattern:
            return False
        return _matches_regex(truncated, pattern, case_sensitive)

    logger.warning("chatbots.matcher.unknown_mode bot=%s mode=%s", bot.id, mode)
    return False


# --- Public entry points --------------------------------------------------


async def find_matching_bots(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: str,
    text: str | None,
    is_first_message: bool,
) -> list[Chatbot]:
    """Return every live bot whose trigger matches this inbound,
    sorted by ``priority DESC, created_at ASC``. Empty list on no
    match."""
    candidates = await _dal.list_live_bots_for_channel(
        session,
        org_id=org_id,
        channel=channel,
    )
    return [b for b in candidates if _bot_matches(b, text, is_first_message)]


async def has_any_matching_bot(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: str,
    text: str | None,
    is_first_message: bool,
) -> bool:
    """Sync-caller-friendly pre-check for
    :mod:`conversations.service`'s precedence rule (Decision §12).
    Short-circuits on the first match — cheaper than the full
    matcher pass when the answer is "yes"."""
    candidates = await _dal.list_live_bots_for_channel(
        session,
        org_id=org_id,
        channel=channel,
    )
    for bot in candidates:
        if _bot_matches(bot, text, is_first_message):
            return True
    return False


async def on_inbound(envelope: dict[str, Any]) -> None:
    """Bus subscriber. Fires for every published
    ``whatsapp.message_received`` or ``email.message_received``
    envelope.

    Opens its own DB session so the publisher's transaction isn't
    held across the matcher's queries + engine.start_run's commit.
    All failures are logged + swallowed — a broken matcher must not
    poison other subscribers or roll back the inbound message.
    """
    org_id = _envelope_uuid(envelope, "org_id")
    conversation_id = _envelope_uuid(envelope, "conversation_id")
    contact_id = _envelope_uuid(envelope, "contact_id")
    message_id = _envelope_uuid(envelope, "message_id")
    channel = envelope.get("channel") or ""
    text = envelope.get("text")
    is_first_message = bool(envelope.get("is_first_message"))

    if org_id is None or conversation_id is None:
        logger.debug(
            "chatbots.matcher.skipped_missing_ids envelope=%s",
            {k: v for k, v in envelope.items() if k != "text"},
        )
        return

    from src.app.shared.context import RequestContext, reset_context, set_context
    from src.app.shared.db import async_session

    token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            # --- Opt-out gate (Decision §11) --------------------------
            if contact_id is not None:
                opted_out = await wf_compliance._check_opt_out(
                    session,
                    contact_id=contact_id,
                    channel=channel,
                )
                if opted_out:
                    _dal.insert_trigger_diagnostic(
                        session,
                        org_id=org_id,
                        bot_id=None,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        reason="opted_out",
                        detail=f"channel={channel}",
                    )
                    await session.commit()
                    return

                blocked = await wf_compliance._check_block_list(
                    session,
                    org_id=org_id,
                    contact_id=contact_id,
                )
                if blocked:
                    _dal.insert_trigger_diagnostic(
                        session,
                        org_id=org_id,
                        bot_id=None,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        reason="blocked",
                    )
                    await session.commit()
                    return

            # --- Parked-run resume takes priority over trigger match --
            # A run parked at a button/list/ask-question node is waiting
            # for THIS user's reply. The reply text (e.g. the tapped
            # button title "Buy Property") almost never matches a bot
            # trigger keyword, so without this check every reply falls
            # through to ``no_match`` and the parked run sits forever.
            parked_runs = await _dal.list_parked_runs_for_conversation(
                session, conversation_id=conversation_id
            )
            if parked_runs:
                parked = max(parked_runs, key=lambda r: r.started_at)
                _dal.insert_trigger_diagnostic(
                    session,
                    org_id=org_id,
                    bot_id=parked.chatbot_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    reason="active_run_exists",
                    detail=f"resuming parked run {parked.id}",
                )
                await session.commit()
                await _engine.resume_run(
                    session,
                    run_id=parked.id,
                    resume_event={
                        "text": text,
                        "message_id": str(message_id) if message_id else None,
                    },
                )
                return

            # --- Matcher pass ----------------------------------------
            matches = await find_matching_bots(
                session,
                org_id=org_id,
                channel=channel,
                text=text,
                is_first_message=is_first_message,
            )
            if not matches:
                _dal.insert_trigger_diagnostic(
                    session,
                    org_id=org_id,
                    bot_id=None,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    reason="no_match",
                )
                await session.commit()
                return

            winner = matches[0]

            # Record skip-diagnostics for losers so operators can see
            # which bot won and why. Batched with the same commit.
            for loser in matches[1:]:
                _dal.insert_trigger_diagnostic(
                    session,
                    org_id=org_id,
                    bot_id=loser.id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    reason="skipped_by_priority",
                    detail=f"winner={winner.id}",
                )

            # --- Idempotency guard (Case #1) --------------------------
            # If an active run already exists for this bot on this
            # conversation, wake the parked run with the new inbound
            # instead of starting a fresh run. Step 6's resume_run
            # sets ``context.resumed_from_park`` so the parked node
            # handler interprets ``last_inbound_text`` as the reply
            # to its prompt.
            active_run = await _dal.get_active_run_for_bot_conversation(
                session,
                org_id=org_id,
                bot_id=winner.id,
                conversation_id=conversation_id,
            )
            if active_run is not None:
                _dal.insert_trigger_diagnostic(
                    session,
                    org_id=org_id,
                    bot_id=winner.id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    reason="active_run_exists",
                    detail=f"resuming parked run {active_run.id}",
                )
                await session.commit()
                await _engine.resume_run(
                    session,
                    run_id=active_run.id,
                    resume_event={
                        "text": text,
                        "message_id": str(message_id) if message_id else None,
                    },
                )
                return

            # --- Fire the run ---------------------------------------
            _dal.insert_trigger_diagnostic(
                session,
                org_id=org_id,
                bot_id=winner.id,
                conversation_id=conversation_id,
                message_id=message_id,
                reason="matched_and_dispatched",
            )
            await session.commit()

            await _engine.start_run(session, bot=winner, event=envelope)
    except Exception:  # noqa: BLE001
        logger.exception(
            "chatbots.matcher.on_inbound_failed org=%s conv=%s msg=%s",
            org_id,
            conversation_id,
            message_id,
        )
    finally:
        reset_context(token)


def _envelope_uuid(envelope: dict[str, Any], key: str) -> uuid.UUID | None:
    raw = envelope.get(key)
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


# --- Startup registration -------------------------------------------------


def register_bus_subscribers() -> None:
    """Register :func:`on_inbound` for the two chatbot trigger event
    types. Called from :mod:`core.chatbots.__init__` at import time
    — the same side-effect pattern the automation module uses."""
    events_bus.subscribe(WHATSAPP_MESSAGE_RECEIVED, on_inbound)
    events_bus.subscribe(EMAIL_MESSAGE_RECEIVED, on_inbound)
