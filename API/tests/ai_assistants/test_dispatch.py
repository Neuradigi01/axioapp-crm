"""Tests for the omnichannel AI dispatch
(``tasks/ai-assistants-omnichannel`` Step 5).

Pure-function tests for the handover keyword matcher + shallow smoke
tests for the dispatch shim. Deep integration (LLM invocation +
adapter send) is covered by the existing WhatsApp AI handler test
suite; this file only asserts the new gates land in the right order.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


# --- Handover keyword matcher (pure function) -------------------------


def test_handover_matches_default_keyword() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Please talk to a human, this bot is useless")
    assert matches("HUMAN PLEASE")  # case-insensitive
    assert matches("Can I speak to a person?")


def test_handover_no_match_on_regular_text() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Hi, do you have leather sofas?") is False
    assert matches("What's your return policy") is False


def test_handover_matches_operator_extra_keyword() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("नमस्ते, मुझे इंसान से बात करनी है", extra_keywords=["इंसान से बात"]) is True


def test_handover_ignores_blank_extras() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches("Hi there", extra_keywords=["", "  "]) is False


def test_handover_none_or_empty_returns_false() -> None:
    from src.app.core.ai_assistants.handover import matches

    assert matches(None) is False
    assert matches("") is False


# --- Dispatch shim (gate order) ---------------------------------------


class _FakeConversation(SimpleNamespace):
    """Minimal stand-in for the ``Conversation`` ORM row so we can
    exercise the dispatch's gates without a real DB session. The
    dispatch treats it as an attribute bag — ``ai_paused``,
    ``ai_handling``, ``id``, ``org_id``."""


@pytest.fixture
def fake_conv() -> _FakeConversation:
    return _FakeConversation(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        ai_paused=False,
        ai_handling=False,
    )


async def test_dispatch_skips_when_paused(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_conv.ai_paused = True
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with patch(
        "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
    ) as bound_mock:
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        # Paused short-circuits BEFORE the binding lookup.
        bound_mock.assert_not_called()


async def test_dispatch_auto_pauses_on_handover_keyword(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)
    fake_session.commit = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.conversations.service.apply_auto_pause",
            new=AsyncMock(return_value=True),
        ) as pause_mock,
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel"
        ) as bound_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="please talk to a human",
        )
        pause_mock.assert_awaited_once()
        # Handover fires BEFORE the binding lookup, and definitely
        # before the reply pipeline delegates.
        bound_mock.assert_not_called()


async def test_dispatch_delegates_when_bound_assistant_exists(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    fake_bound_assistant = SimpleNamespace(id=uuid.uuid4(), name="Test")

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=fake_bound_assistant),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(return_value=None),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Do you have leather sofas?",
        )
        legacy_mock.assert_awaited_once()


async def test_dispatch_skips_when_no_bound_and_ai_handling_false(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        legacy_mock.assert_not_called()


async def test_dispatch_delegates_legacy_when_ai_handling_true(fake_conv) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import dispatch

    fake_conv.ai_handling = True
    fake_session = AsyncMock()
    fake_session.refresh = AsyncMock(return_value=None)

    with (
        patch(
            "src.app.core.ai_assistants.data_access.find_active_assistant_bound_to_channel",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.app.core.integrations.whatsapp.ai_handler.dispatch_ai_response",
            new=AsyncMock(),
        ) as legacy_mock,
    ):
        await dispatch.route_whatsapp_inbound(
            fake_session,
            conversation=fake_conv,
            inbound_text="Hi",
        )
        legacy_mock.assert_awaited_once()


async def test_email_route_is_noop() -> None:
    from src.app.core.ai_assistants import dispatch

    fake_session = AsyncMock()
    fake_conv = _FakeConversation(id=uuid.uuid4(), org_id=uuid.uuid4())
    # Should return without touching the session or any dispatch machinery.
    result = await dispatch.route_email_inbound(
        fake_session, conversation=fake_conv, inbound_text="Please help"
    )
    assert result is None
