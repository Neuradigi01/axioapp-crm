"""whatsapp-platform-upgrade Step 19 — AI agent wiring tests.

Pure-Python boundary tests around the AI module's heuristic stub,
the history-projection helper, the handover-keyword matcher, and the
``AISettingsPatch`` schema validation.

The handler pipeline (``dispatch_ai_response``) calls the WhatsApp
adapter + writes rows — those paths are exercised by the integration
smoke flow against a live DB once the migration lands. Here we cover
the deterministic pieces that don't need a session.

Cases:
  1. ``AIResponse`` defaults: handover=False, metadata={}.
  2. ``history_from_messages`` skips internal notes (Step 13 contract).
  3. ``history_from_messages`` caps at ``max_turns`` newest-last.
  4. ``history_from_messages`` maps direction -> role (in=user, out=assistant).
  5. ``generate_response`` returns high confidence on a greeting.
  6. ``generate_response`` flags handover on a price question.
  7. ``generate_response`` flags handover on explicit operator phrasing.
  8. ``generate_response`` returns low confidence on rambling messages.
  9. ``_matches_handover_keyword`` is case-insensitive + substring-aware.
 10. ``_matches_handover_keyword`` returns False on empty inputs.
 11. ``AISettingsPatch`` rejects confidence threshold outside [0,1].
 12. ``AISettingsPatch`` rejects keyword list > 50.
 13. ``AISettingsPatch`` rejects system prompt > 4096 chars.
 14. ``AISettingsPatch`` accepts all-None (partial update sentinel).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import pytest
from pydantic import ValidationError

from src.app.core.ai.whatsapp_integration import (
    AIResponse,
    ConversationTurn,
    generate_response,
    history_from_messages,
)
from src.app.core.integrations.whatsapp.ai_handler import (
    _matches_handover_keyword,
)
from src.app.core.integrations.whatsapp.schemas import AISettingsPatch


@dataclass
class _FakeMessage:
    """Minimal stand-in for the ``Message`` ORM row — only the four
    attributes ``history_from_messages`` reads."""

    direction: str
    text: Optional[str]
    is_internal: bool = False


def _run(coro):
    return asyncio.run(coro)


class TestAIResponseDataclass:
    def test_defaults(self):
        r = AIResponse(text="hi", confidence=0.9)
        assert r.handover_requested is False
        assert r.metadata == {}


class TestHistoryProjection:
    def test_skips_internal_notes(self):
        msgs = [
            _FakeMessage(direction="in", text="hi"),
            _FakeMessage(direction="out", text="op note", is_internal=True),
            _FakeMessage(direction="out", text="real reply"),
        ]
        out = history_from_messages(msgs)
        assert [t.text for t in out] == ["hi", "real reply"]

    def test_caps_to_max_turns_newest_last(self):
        msgs = [
            _FakeMessage(direction="in", text=f"msg-{i}") for i in range(30)
        ]
        out = history_from_messages(msgs, max_turns=5)
        assert len(out) == 5
        # Newest last — the last entry must be the highest-index message.
        assert out[-1].text == "msg-29"

    def test_direction_maps_to_role(self):
        msgs = [
            _FakeMessage(direction="in", text="customer"),
            _FakeMessage(direction="out", text="staff"),
        ]
        out = history_from_messages(msgs)
        assert out[0].role == "user"
        assert out[1].role == "assistant"

    def test_skips_empty_text(self):
        msgs = [
            _FakeMessage(direction="in", text=None),
            _FakeMessage(direction="in", text=""),
            _FakeMessage(direction="in", text="ok"),
        ]
        out = history_from_messages(msgs)
        assert [t.text for t in out] == ["ok"]


class TestGenerateResponseHeuristic:
    def test_greeting_high_confidence(self):
        r = _run(
            generate_response(
                system_prompt=None,
                history=[],
                latest_inbound_text="Hi there",
            )
        )
        assert r.confidence >= 0.8
        assert r.handover_requested is False

    def test_price_question_triggers_handover(self):
        r = _run(
            generate_response(
                system_prompt=None,
                history=[],
                latest_inbound_text="How much is the sofa?",
            )
        )
        assert r.handover_requested is True

    def test_operator_phrase_triggers_handover(self):
        r = _run(
            generate_response(
                system_prompt=None,
                history=[],
                latest_inbound_text="I want to speak to a manager.",
            )
        )
        assert r.handover_requested is True

    def test_rambling_low_confidence(self):
        long_text = " ".join(["word"] * 40)
        r = _run(
            generate_response(
                system_prompt=None,
                history=[],
                latest_inbound_text=long_text,
            )
        )
        assert r.confidence < 0.5

    def test_hours_returns_no_handover(self):
        r = _run(
            generate_response(
                system_prompt=None,
                history=[],
                latest_inbound_text="What are your business hours?",
            )
        )
        assert r.handover_requested is False
        assert r.confidence >= 0.8


class TestHandoverKeywordMatcher:
    def test_case_insensitive_substring(self):
        assert _matches_handover_keyword(
            "Please get me a HUMAN agent",
            ["human"],
        )

    def test_empty_text(self):
        assert _matches_handover_keyword("", ["human"]) is False

    def test_empty_keywords(self):
        assert _matches_handover_keyword("anything", []) is False

    def test_no_match(self):
        assert (
            _matches_handover_keyword(
                "what time do you open?", ["human", "agent"]
            )
            is False
        )

    def test_ignores_blank_keyword_entries(self):
        # Real config may have leading/trailing blank lines from the
        # textarea — these should not blanket-match every message.
        assert (
            _matches_handover_keyword("hello", ["", "  ", "human"])
            is False
        )


class TestAISettingsPatch:
    def test_threshold_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            AISettingsPatch(ai_confidence_threshold=1.5)
        with pytest.raises(ValidationError):
            AISettingsPatch(ai_confidence_threshold=-0.1)

    def test_keyword_list_cap(self):
        with pytest.raises(ValidationError):
            AISettingsPatch(
                ai_handover_keywords=[f"kw-{i}" for i in range(51)]
            )

    def test_system_prompt_max_length(self):
        with pytest.raises(ValidationError):
            AISettingsPatch(ai_system_prompt="x" * 4097)

    def test_all_none_partial_update(self):
        patch = AISettingsPatch()
        assert patch.ai_handling_default_enabled is None
        assert patch.ai_confidence_threshold is None
        assert patch.ai_handover_keywords is None
        assert patch.ai_system_prompt is None

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AISettingsPatch.model_validate(
                {"ai_confidence_threshold": 0.7, "bogus": True}
            )

    def test_valid_payload(self):
        patch = AISettingsPatch(
            ai_handling_default_enabled=True,
            ai_confidence_threshold=0.75,
            ai_handover_keywords=["human", "agent"],
            ai_system_prompt="You are a helpful assistant.",
        )
        assert patch.ai_confidence_threshold == 0.75
        assert patch.ai_handover_keywords == ["human", "agent"]
