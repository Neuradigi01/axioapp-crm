"""Tests for the email threading helpers
(``tasks/ai-assistants-omnichannel`` Step 6).

Pure-function tests for ``reply_subject`` / ``references_chain`` /
``build_reply_thread``. No DB, no async, no fixtures — call the
function, assert the shape.
"""

from __future__ import annotations

from src.app.core.ai_assistants.email_threading import (
    build_reply_thread,
    references_chain,
    reply_subject,
)


# --- reply_subject -------------------------------------------------------


def test_reply_subject_adds_re_prefix() -> None:
    assert reply_subject("Question about pricing") == "Re: Question about pricing"


def test_reply_subject_idempotent_on_existing_re() -> None:
    assert reply_subject("Re: Question about pricing") == "Re: Question about pricing"


def test_reply_subject_collapses_multiple_re() -> None:
    assert reply_subject("Re: RE: re: Question") == "Re: Question"


def test_reply_subject_none_or_blank_falls_back() -> None:
    assert reply_subject(None) == "Re: (no subject)"
    assert reply_subject("") == "Re: (no subject)"
    assert reply_subject("   ") == "Re: (no subject)"


def test_reply_subject_only_re_falls_back() -> None:
    assert reply_subject("Re: Re: Re:") == "Re: (no subject)"


# --- references_chain ---------------------------------------------------


def test_references_chain_extends_existing() -> None:
    result = references_chain(
        "<root@customer.com> <mid@customer.com>",
        "<latest@customer.com>",
    )
    assert result == "<root@customer.com> <mid@customer.com> <latest@customer.com>"


def test_references_chain_no_existing() -> None:
    assert references_chain(None, "<latest@customer.com>") == "<latest@customer.com>"
    assert references_chain("", "<latest@customer.com>") == "<latest@customer.com>"


def test_references_chain_no_message_id_returns_existing() -> None:
    assert references_chain("<root@customer.com>", None) == "<root@customer.com>"


def test_references_chain_both_missing_is_none() -> None:
    assert references_chain(None, None) is None


# --- build_reply_thread -------------------------------------------------


def test_build_reply_thread_full_shape() -> None:
    result = build_reply_thread(
        ai_reply_text="Yes, our Starter plan is $29/user/month for up to 5 users.",
        inbound_subject="Question about pricing",
        inbound_message_id="<abc-123@customer.com>",
        inbound_references="<root@customer.com>",
        inbound_body_text="Hi, do you have a plan for 5 users?\n\nThanks,\nJane",
    )
    assert result.subject == "Re: Question about pricing"
    assert result.in_reply_to == "<abc-123@customer.com>"
    assert result.references == "<root@customer.com> <abc-123@customer.com>"
    # Body is the AI reply only — threading rides on the RFC 5322
    # headers, no ``--- Original message ---`` block appended.
    assert result.body == "Yes, our Starter plan is $29/user/month for up to 5 users."
    assert "--- Original message ---" not in result.body
    assert "> Hi, do you have a plan for 5 users?" not in result.body


def test_build_reply_thread_no_message_id_omits_in_reply_to() -> None:
    result = build_reply_thread(
        ai_reply_text="Reply text",
        inbound_subject="Original",
        inbound_message_id=None,
        inbound_references=None,
        inbound_body_text="Body",
    )
    assert result.in_reply_to is None
    assert result.references is None


def test_build_reply_thread_idempotent_subject() -> None:
    # Reply-to-a-reply: subject already has "Re:", must not double it.
    result = build_reply_thread(
        ai_reply_text="…",
        inbound_subject="Re: Question about pricing",
        inbound_message_id="<second@customer.com>",
        inbound_references="<root@customer.com> <first@customer.com>",
        inbound_body_text="…",
    )
    assert result.subject == "Re: Question about pricing"
    assert result.references == "<root@customer.com> <first@customer.com> <second@customer.com>"
