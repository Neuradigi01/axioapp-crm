"""Step 4 tests — event catalog + SPF/DKIM pass logic.

Pure-Python; no DB. Full webhook / receive_email end-to-end tests
(cross-tenant rejection, first-message flag, regression on inline
auto-reply) live in ``test_inbound_events_db.py`` and need the
async DB fixture + a mock event bus — deferred to the batch pytest
run per memory ``feedback_pause_before_pytest.md``.
"""

from __future__ import annotations

import pytest

from src.app.core.conversations.adapters.email import _email_auth_passed
from src.app.core.events import event_catalog


def test_email_message_received_in_event_catalog() -> None:
    assert event_catalog.EMAIL_MESSAGE_RECEIVED == "email.message_received"


def test_email_message_received_registered_in_all_events() -> None:
    assert event_catalog.EMAIL_MESSAGE_RECEIVED in event_catalog.ALL_EVENTS


def test_email_message_received_has_description() -> None:
    desc = event_catalog.EVENT_DESCRIPTIONS.get(event_catalog.EMAIL_MESSAGE_RECEIVED)
    assert desc == "Inbound email from a contact."


def test_email_message_received_exported() -> None:
    assert "EMAIL_MESSAGE_RECEIVED" in event_catalog.__all__


# --- SPF / DKIM verdict parser --------------------------------------------


def test_auth_passed_when_header_missing() -> None:
    """A missing Authentication-Results header is treated as pass —
    legit inbound from a bare SMTP server shouldn't be dropped."""
    assert _email_auth_passed({}) is True


def test_auth_passed_on_all_pass_verdict() -> None:
    headers = {
        "authentication-results": "mx.google.com; spf=pass smtp.mailfrom=bob@example.com; dkim=pass header.i=@example.com; dmarc=pass"
    }
    assert _email_auth_passed(headers) is True


def test_auth_fails_on_spf_fail() -> None:
    headers = {"authentication-results": "mx.google.com; spf=fail; dkim=pass"}
    assert _email_auth_passed(headers) is False


def test_auth_fails_on_spf_softfail() -> None:
    headers = {"authentication-results": "mx.google.com; spf=softfail; dkim=pass"}
    assert _email_auth_passed(headers) is False


def test_auth_fails_on_dkim_fail() -> None:
    headers = {"authentication-results": "mx.google.com; spf=pass; dkim=fail"}
    assert _email_auth_passed(headers) is False


def test_auth_fails_on_dmarc_fail() -> None:
    headers = {"authentication-results": "mx.google.com; spf=pass; dkim=pass; dmarc=fail"}
    assert _email_auth_passed(headers) is False


def test_auth_case_insensitive() -> None:
    """The header name arrives in various cases from different
    providers (Gmail lowercases, Outlook title-cases)."""
    headers = {"Authentication-Results": "mx.outlook.com; SPF=FAIL"}
    assert _email_auth_passed(headers) is False


@pytest.mark.parametrize(
    "verdict_line",
    [
        "spf=neutral",       # neutral is not a fail
        "spf=none",          # no policy found
        "dkim=neutral",
        "dkim=none",
        "arc=pass",          # ARC is a separate spec; we don't gate on it
    ],
)
def test_auth_passes_on_non_fail_verdicts(verdict_line: str) -> None:
    """Only explicit `fail` / `softfail` / `dmarc=fail` short-circuits.
    Neutral / none / arc-only headers are treated as pass to avoid
    dropping legit inbound over metadata gaps."""
    assert _email_auth_passed({"authentication-results": verdict_line}) is True
