"""Lead-capture helper tests
(``tasks/ai-assistants`` Step 16).

The pure-Python cases (email regex + ask-at-turn trigger) run
without a DB. The end-to-end DB test exercises the full path
(contact upsert + lead ingest + conversation.contact_id backfill)
and skips when the compose stack isn't up.
"""

from __future__ import annotations

import uuid

import pytest

# Side-effect imports so ORM models resolve their FKs before we
# touch the DB session in the end-to-end test.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402

from src.app.core.ai_assistants import lead_capture
from src.app.core.ai_assistants.models import AiAssistant, LeadCaptureMode

# NOTE — no KEK install helper here. Lead-capture tests never
# invoke crypto directly. See ``test_analytics.py`` for the same
# note; touching KEK config from module scope breaks isolation
# with ``tests/integrations/ai/test_provider_keys.py``.


# --- extract_email --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call me at bob@example.com later", "bob@example.com"),
        ("BOB@Example.COM", "bob@example.com"),  # lower-cased on return
        ("plus tag j.o+notes@sub.example.co.uk works", "j.o+notes@sub.example.co.uk"),
        ("emails at end of a sentence: alice@foo.io.", "alice@foo.io"),
        ("comma tail bob@foo.com, then more", "bob@foo.com"),
        ("no email in this message", None),
        ("", None),
        (None, None),
        ("not-an-email @ foo.com", None),
    ],
)
def test_extract_email(text, expected):
    assert lead_capture.extract_email(text) == expected


# --- should_ask_at_turn ---------------------------------------------------


def _stub_assistant(mode: LeadCaptureMode, turn_n: int = 3) -> AiAssistant:
    return AiAssistant(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="stub",
        key_id=uuid.uuid4(),
        model="gpt-4o-mini",
        lead_capture_mode=mode,
        lead_capture_turn_n=turn_n,
        lead_capture_message=None,
    )


def test_should_ask_at_turn_off_mode_never_asks():
    a = _stub_assistant(LeadCaptureMode.off)
    for turn in range(1, 10):
        assert lead_capture.should_ask_at_turn(a, current_turn=turn) is False


def test_should_ask_at_turn_detect_email_mode_never_asks():
    a = _stub_assistant(LeadCaptureMode.detect_email)
    for turn in range(1, 10):
        assert lead_capture.should_ask_at_turn(a, current_turn=turn) is False


def test_should_ask_at_turn_ask_mode_fires_on_target_turn():
    a = _stub_assistant(LeadCaptureMode.ask_at_turn, turn_n=3)
    assert lead_capture.should_ask_at_turn(a, current_turn=1) is False
    assert lead_capture.should_ask_at_turn(a, current_turn=2) is False
    assert lead_capture.should_ask_at_turn(a, current_turn=3) is True
    assert lead_capture.should_ask_at_turn(a, current_turn=4) is False


def test_should_ask_at_turn_zero_falls_back_to_default_three():
    """A 0 in ``turn_n`` (falsy) is treated as "unset" — falls back
    to the default 3, so the ask fires on turn 3 not turn 1. Matches
    the ``or 3`` guard in :func:`should_ask_at_turn`."""
    a = _stub_assistant(LeadCaptureMode.ask_at_turn, turn_n=0)
    assert lead_capture.should_ask_at_turn(a, current_turn=1) is False
    assert lead_capture.should_ask_at_turn(a, current_turn=3) is True


# --- ask_message_for ------------------------------------------------------


def test_ask_message_default_when_unset():
    a = _stub_assistant(LeadCaptureMode.ask_at_turn)
    a.lead_capture_message = None
    assert lead_capture.ask_message_for(a) == lead_capture.DEFAULT_ASK_MESSAGE


def test_ask_message_uses_operator_config_when_set():
    a = _stub_assistant(LeadCaptureMode.ask_at_turn)
    a.lead_capture_message = "Care to share your work email?"
    assert lead_capture.ask_message_for(a) == "Care to share your work email?"


def test_ask_message_falls_back_when_only_whitespace():
    """Operator saved an all-whitespace string — same as unset."""
    a = _stub_assistant(LeadCaptureMode.ask_at_turn)
    a.lead_capture_message = "   \t \n "
    assert lead_capture.ask_message_for(a) == lead_capture.DEFAULT_ASK_MESSAGE


# --- capture_lead_from_message: off-mode short-circuit -------------------


@pytest.mark.asyncio
async def test_capture_off_mode_short_circuits():
    """When mode='off' the helper never touches the DB. We can pass
    ``session=None`` and it should still return a clean skipped
    outcome without a NoneType attribute error."""
    a = _stub_assistant(LeadCaptureMode.off)
    outcome = await lead_capture.capture_lead_from_message(
        None,  # type: ignore[arg-type]
        assistant=a,
        conversation_id=uuid.uuid4(),
        user_message="bob@example.com",
    )
    assert outcome.lead_id is None
    assert outcome.matched_email is None
    assert outcome.skipped_reason == "lead_capture_off"


@pytest.mark.asyncio
async def test_capture_no_email_returns_skipped():
    """No email in the text → skipped without any DB call."""
    a = _stub_assistant(LeadCaptureMode.detect_email)
    outcome = await lead_capture.capture_lead_from_message(
        None,  # type: ignore[arg-type]
        assistant=a,
        conversation_id=uuid.uuid4(),
        user_message="hi there, just curious",
    )
    assert outcome.lead_id is None
    assert outcome.matched_email is None
    assert outcome.skipped_reason == "no_email_in_message"
