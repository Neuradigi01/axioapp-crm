"""Pydantic schema tests — Step 2. Pure Python, no DB."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.chatbots.schemas import (
    ChatbotCreate,
    ChatbotGraph,
    ChatbotUpdate,
    TriggerConfig,
)


def test_trigger_config_defaults_to_any_channel_any_mode() -> None:
    tc = TriggerConfig()
    assert tc.channel == "any"
    assert tc.mode == "any"
    assert tc.keywords == []
    assert tc.regex_pattern is None
    assert tc.case_sensitive is False
    assert tc.first_message_only is False


def test_trigger_keyword_mode_requires_keywords() -> None:
    with pytest.raises(ValidationError, match="requires at least one keyword"):
        TriggerConfig(mode="keyword", keywords=[])


def test_trigger_regex_mode_requires_pattern() -> None:
    with pytest.raises(ValidationError, match="requires regex_pattern"):
        TriggerConfig(mode="regex", regex_pattern=None)


def test_trigger_regex_pattern_capped_at_500_chars() -> None:
    long_pattern = "a" * 501
    with pytest.raises(ValidationError):
        TriggerConfig(mode="regex", regex_pattern=long_pattern)


def test_trigger_keyword_trimmed_and_deduped_empty_strings_dropped() -> None:
    tc = TriggerConfig(
        mode="keyword",
        keywords=["hey", "  hello  ", "", "   ", "hi"],
    )
    assert tc.keywords == ["hey", "hello", "hi"]


def test_trigger_keyword_over_100_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="keyword too long"):
        TriggerConfig(mode="keyword", keywords=["a" * 101])


def test_trigger_bad_channel_rejected() -> None:
    with pytest.raises(ValidationError):
        TriggerConfig(channel="sms")


def test_chatbot_update_requires_expected_version() -> None:
    with pytest.raises(ValidationError, match="expected_version"):
        ChatbotUpdate()  # type: ignore[call-arg]


def test_chatbot_create_defaults_are_sane() -> None:
    payload = ChatbotCreate(name="Test bot")
    assert payload.category == "Custom"
    assert payload.priority == 100
    assert isinstance(payload.trigger_config, TriggerConfig)
    assert isinstance(payload.graph, ChatbotGraph)


def test_chatbot_graph_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatbotGraph.model_validate(
            {"nodes": [], "edges": [], "extra_field": "not allowed"}
        )
