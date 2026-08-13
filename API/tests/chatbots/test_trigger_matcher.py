"""Trigger-matcher primitive tests — pure Python.

Covers the sync matching functions in
:mod:`core.chatbots.trigger_matcher` that don't need a DB. Full
bus-integration tests (opt-out gate → matcher → engine.start_run
end-to-end, idempotency guard, precedence pre-check in
receive_webhook) live in ``test_trigger_matcher_db.py`` and need the
async DB fixture — deferred to the batch pytest run per memory
``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from src.app.core.chatbots import trigger_matcher as tm
from src.app.core.chatbots.trigger_matcher import (
    UnsafeRegex,
    _bot_matches,
    _matches_keyword,
    _matches_regex,
    lint_regex_pattern,
)


def _bot(trigger_config: dict, priority: int = 100) -> SimpleNamespace:
    """Lightweight Chatbot stand-in for the pure-Python matcher tests."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        priority=priority,
        trigger_config=trigger_config,
    )


# --- Keyword matcher ------------------------------------------------------


def test_keyword_case_insensitive_by_default() -> None:
    assert _matches_keyword("Hey there", ["hey"], case_sensitive=False) is True
    assert _matches_keyword("HEY THERE", ["hey"], case_sensitive=False) is True


def test_keyword_case_sensitive_when_flag_set() -> None:
    assert _matches_keyword("Hey there", ["hey"], case_sensitive=True) is False
    assert _matches_keyword("hey there", ["hey"], case_sensitive=True) is True


def test_keyword_word_boundary_left() -> None:
    """'hi' inside 'this' must NOT match — protects against 'no' matching 'know'."""
    assert _matches_keyword("this is a test", ["hi"], case_sensitive=False) is False


def test_keyword_word_boundary_right() -> None:
    assert _matches_keyword("help me now", ["help"], case_sensitive=False) is True
    assert _matches_keyword("helper needed", ["help"], case_sensitive=False) is False


def test_keyword_multiple_first_match_wins() -> None:
    assert (
        _matches_keyword("pricing please", ["hey", "hello", "pricing"], case_sensitive=False)
        is True
    )


def test_keyword_empty_list_never_matches() -> None:
    assert _matches_keyword("any text", [], case_sensitive=False) is False


def test_keyword_empty_string_in_list_ignored() -> None:
    assert _matches_keyword("hey", ["", "hey"], case_sensitive=False) is True


# --- Regex matcher --------------------------------------------------------


def test_regex_case_sensitive_true() -> None:
    assert _matches_regex("help me", r"^help\b", case_sensitive=True) is True
    assert _matches_regex("Help me", r"^help\b", case_sensitive=True) is False


def test_regex_case_sensitive_false() -> None:
    assert _matches_regex("Help me", r"^help\b", case_sensitive=False) is True


def test_regex_no_match_returns_false() -> None:
    assert _matches_regex("hello", r"^pricing", case_sensitive=False) is False


def test_regex_invalid_pattern_returns_false_not_raise() -> None:
    """A malformed pattern at runtime must not kill the matcher."""
    assert _matches_regex("anything", r"[unclosed", case_sensitive=False) is False


def test_regex_redos_safe_on_moderate_input() -> None:
    """Pathological pattern on a large-ish input must finish quickly.

    With ``google-re2`` installed this is trivially <1ms. Without
    it (Windows dev fallback), the save-time linter should have
    rejected the pattern via :func:`lint_regex_pattern` — but
    :func:`_matches_regex` still shouldn't hang on 5 KB of ``a``s.
    Threshold is generous (500ms) so the test doesn't flake on
    slow CI runners.
    """
    hostile = "a" * 5000
    start = time.perf_counter()
    result = _matches_regex(hostile + "b", r"^(a+)+$", case_sensitive=False)
    elapsed = time.perf_counter() - start
    # We don't care what result is — only that we return within
    # bounded time and don't hang. On re2 result is False (no b at
    # end matches greedy prefix); on Python re either False or
    # timeout — the linter would have rejected this pattern at
    # save-time, so runtime hits it only via legacy data.
    del result
    assert elapsed < 0.5, f"regex match took {elapsed:.3f}s (should be <0.5s)"


# --- Regex linter ---------------------------------------------------------


def test_linter_accepts_safe_patterns() -> None:
    lint_regex_pattern(r"^help\b")
    lint_regex_pattern(r"pricing|quote|demo")
    lint_regex_pattern(r"[A-Za-z]+ order #\d+")


def test_linter_rejects_nested_quantifier_when_no_re2() -> None:
    """When we're on the Python-``re`` fallback, catastrophic-
    backtracking shapes get 422'd at save time."""
    if tm._RE2_AVAILABLE:
        # re2 is safe against ReDoS; the linter accepts anything
        # that re2 will compile. Skip the fail check.
        pytest.skip("google-re2 present; linter is permissive")
    with pytest.raises(UnsafeRegex):
        lint_regex_pattern(r"^(a+)+$")


def test_linter_rejects_malformed_pattern() -> None:
    with pytest.raises(UnsafeRegex):
        lint_regex_pattern(r"[unclosed")


# --- Per-bot evaluator ---------------------------------------------------


def test_bot_matches_mode_any_always_matches() -> None:
    bot = _bot({"mode": "any", "channel": "any"})
    assert _bot_matches(bot, text="anything", is_first_message=False) is True
    assert _bot_matches(bot, text=None, is_first_message=False) is True


def test_bot_matches_first_message_only_true_gate() -> None:
    bot = _bot({"mode": "any", "channel": "any", "first_message_only": True})
    assert _bot_matches(bot, text="hey", is_first_message=True) is True
    assert _bot_matches(bot, text="hey", is_first_message=False) is False


def test_bot_matches_keyword_mode() -> None:
    bot = _bot({"mode": "keyword", "keywords": ["pricing"], "case_sensitive": False})
    assert _bot_matches(bot, text="pricing please", is_first_message=False) is True
    assert _bot_matches(bot, text="hello", is_first_message=False) is False


def test_bot_matches_regex_mode() -> None:
    bot = _bot(
        {
            "mode": "regex",
            "regex_pattern": r"^help\b",
            "case_sensitive": False,
        }
    )
    assert _bot_matches(bot, text="Help me", is_first_message=False) is True
    assert _bot_matches(bot, text="I need help", is_first_message=False) is False


def test_bot_matches_regex_missing_pattern_returns_false() -> None:
    bot = _bot({"mode": "regex", "regex_pattern": None, "case_sensitive": False})
    assert _bot_matches(bot, text="anything", is_first_message=False) is False


def test_bot_matches_text_truncated_to_4kb() -> None:
    """Case #19 — matcher truncates inbound text to 4 KB. A keyword
    past the 4 KB boundary must NOT match."""
    prefix = "x" * (5 * 1024)  # 5 KB of noise
    text = prefix + " needle"
    bot = _bot({"mode": "keyword", "keywords": ["needle"], "case_sensitive": False})
    assert _bot_matches(bot, text=text, is_first_message=False) is False


def test_bot_matches_unknown_mode_returns_false() -> None:
    bot = _bot({"mode": "future_mode_that_doesnt_exist"})
    assert _bot_matches(bot, text="hey", is_first_message=False) is False


# --- Registration surface ------------------------------------------------


def test_register_bus_subscribers_symbol_exists() -> None:
    """Guards that ``__init__.py``'s side-effect import path stays
    stable — if the function is renamed, the package import breaks
    and this test catches it before the app boots."""
    assert callable(tm.register_bus_subscribers)


def test_regex_engine_reports_which_backend_active() -> None:
    """The ``_RE2_AVAILABLE`` module flag is what the linter branches
    on. Presence guarantees the fallback path exists; the actual
    value depends on the environment."""
    assert isinstance(tm._RE2_AVAILABLE, bool)
