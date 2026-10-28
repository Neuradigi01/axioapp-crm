"""whatsapp-platform-upgrade Step 17 — keyword engine tests.

Pure-Python boundary tests around the match helpers + cooldown
cache + schema validation. Integration-style action dispatch is
covered by the broader conversations test suite once the migration
lands.

Cases:
  1. `_match_contains` case-insensitive substring match.
  2. `_match_exact` whole-string match (trimmed, case-insensitive).
  3. `_match_regex` matches a valid pattern.
  4. `_match_regex` returns False on an invalid pattern (no crash).
  5. `_match_regex` rejects an over-length pattern.
  6. Cooldown cache blocks a second hit + expires.
  7. Schema rejects blank keyword.
  8. Schema rejects > 50 keywords.
  9. Schema rejects > 200-char regex keyword.
 10. Schema rejects > 10 actions per rule.
"""

from __future__ import annotations

import time
import uuid

import pytest
from pydantic import ValidationError

from src.app.core.integrations.whatsapp.keyword_engine import (
    _COOLDOWN_CACHE,
    _cooldown_active,
    _match_contains,
    _match_exact,
    _match_regex,
    _set_cooldown,
)
from src.app.core.integrations.whatsapp.schemas import (
    KeywordRuleUpsert,
)


class TestMatchContains:
    def test_simple_hit(self):
        assert _match_contains(["price"], "what's the price?") is True

    def test_case_insensitive(self):
        assert _match_contains(["Price"], "WHAT'S THE PRICE?") is True

    def test_no_match(self):
        assert _match_contains(["price"], "thanks!") is False

    def test_empty_keyword_ignored(self):
        # An empty keyword in the list shouldn't match every message.
        assert _match_contains(["", "price"], "thanks!") is False


class TestMatchExact:
    def test_simple_hit(self):
        assert _match_exact(["yes"], "Yes") is True

    def test_trims_whitespace(self):
        assert _match_exact(["yes"], "  yes  ") is True

    def test_partial_does_not_match(self):
        assert _match_exact(["yes"], "yes please") is False


class TestMatchRegex:
    def test_valid_pattern_matches(self):
        assert _match_regex([r"how (much|long)"], "how much?") is True

    def test_invalid_pattern_returns_false(self):
        # Unterminated character class — would raise re.error.
        assert _match_regex([r"["], "hello") is False

    def test_over_length_pattern_skipped(self):
        # 201-char pattern → schema rejects, but the helper also
        # defensively skips. Test the helper-side guard.
        long_pat = "a" * 201
        assert _match_regex([long_pat], "aaaa") is False

    def test_case_insensitive(self):
        assert _match_regex([r"PRICE"], "what's the price?") is True


class TestCooldownCache:
    def test_first_check_is_clean(self):
        _COOLDOWN_CACHE.clear()
        rid = uuid.uuid4()
        assert _cooldown_active(rid, "alice") is False

    def test_set_then_blocks(self):
        _COOLDOWN_CACHE.clear()
        rid = uuid.uuid4()
        _set_cooldown(rid, "alice")
        assert _cooldown_active(rid, "alice") is True

    def test_does_not_block_other_contact(self):
        _COOLDOWN_CACHE.clear()
        rid = uuid.uuid4()
        _set_cooldown(rid, "alice")
        assert _cooldown_active(rid, "bob") is False

    def test_expired_entry_gced_on_read(self):
        _COOLDOWN_CACHE.clear()
        rid = uuid.uuid4()
        # Force an expired entry directly.
        _COOLDOWN_CACHE[(rid, "alice")] = time.monotonic() - 1.0
        assert _cooldown_active(rid, "alice") is False
        # Entry should have been swept off the dict.
        assert (rid, "alice") not in _COOLDOWN_CACHE


class TestSchemaValidation:
    def test_blank_keyword_rejected(self):
        with pytest.raises(ValidationError):
            KeywordRuleUpsert(
                name="test",
                keywords=["   "],
                match_type="contains",
                actions=[],
            )

    def test_no_keywords_rejected(self):
        with pytest.raises(ValidationError):
            KeywordRuleUpsert(
                name="test",
                keywords=[],
                match_type="contains",
                actions=[],
            )

    def test_too_many_keywords_rejected(self):
        with pytest.raises(ValidationError):
            KeywordRuleUpsert(
                name="test",
                keywords=[f"kw{i}" for i in range(51)],
                match_type="contains",
                actions=[],
            )

    def test_over_length_regex_rejected(self):
        with pytest.raises(ValidationError):
            KeywordRuleUpsert(
                name="test",
                keywords=["a" * 201],
                match_type="regex",
                actions=[],
            )

    def test_too_many_actions_rejected(self):
        with pytest.raises(ValidationError):
            KeywordRuleUpsert(
                name="test",
                keywords=["price"],
                match_type="contains",
                actions=[
                    {
                        "action_type": "reply_text",
                        "action_config": {"text": "ok"},
                        "position": i,
                    }
                    for i in range(11)
                ],
            )

    def test_valid_payload_accepted(self):
        payload = KeywordRuleUpsert(
            name="Pricing query",
            keywords=["price", "rate", "cost"],
            match_type="contains",
            actions=[
                {
                    "action_type": "reply_template",
                    "action_config": {"template_id": str(uuid.uuid4())},
                    "position": 0,
                }
            ],
        )
        assert payload.name == "Pricing query"
        assert len(payload.actions) == 1
