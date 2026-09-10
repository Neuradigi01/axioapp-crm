"""Tests for the email reply-worthiness guardrail
(``tasks/ai-assistants-omnichannel`` Step 6).

Pure-function tests — no DB, no async, no mocking. Each rule in
``is_reply_worthy`` = one assertion. Add a case here first when a
new skip reason lands.
"""

from __future__ import annotations

from src.app.core.ai_assistants.email_guardrails import (
    InboundEmail,
    is_reply_worthy,
    strip_quoted_history,
)


def _real_email(**overrides: object) -> InboundEmail:
    """Build a baseline InboundEmail that PASSES the guardrail — tests
    override one field at a time to isolate the rule under test."""
    defaults: dict[str, object] = dict(
        sender_email="jane@customer.com",
        subject="Question about your pricing",
        body_text=("Hi team,\n\nDo you have a plan for 5 users? Please advise.\n\nThanks,\nJane"),
        headers={},
    )
    defaults.update(overrides)
    return InboundEmail(**defaults)  # type: ignore[arg-type]


# --- Baseline pass -------------------------------------------------------


def test_real_human_email_passes() -> None:
    ok, reason = is_reply_worthy(_real_email())
    assert ok is True
    assert reason is None


def test_real_human_with_reply_chain_passes() -> None:
    # Chained replies are the majority case — must not accidentally
    # get filtered out by any header rule.
    ok, reason = is_reply_worthy(
        _real_email(
            headers={
                "In-Reply-To": "<abc-123@customer.com>",
                "References": "<root@customer.com> <abc-123@customer.com>",
            }
        )
    )
    assert ok is True
    assert reason is None


def test_empty_subject_passes_when_body_real() -> None:
    ok, _ = is_reply_worthy(_real_email(subject=""))
    assert ok is True


# --- Sender local-part deny-list ----------------------------------------


def test_no_reply_sender_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(sender_email="no-reply@amazon.com"))
    assert ok is False
    assert reason == "sender_role_account"


def test_noreply_variant_skipped_case_insensitive() -> None:
    ok, reason = is_reply_worthy(_real_email(sender_email="NOREPLY@Example.COM"))
    assert ok is False
    assert reason == "sender_role_account"


def test_notifications_sender_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(sender_email="notifications@github.com"))
    assert ok is False
    assert reason == "sender_role_account"


def test_mailer_daemon_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(sender_email="mailer-daemon@example.com"))
    assert ok is False
    assert reason == "sender_role_account"


# --- RFC header rules ----------------------------------------------------


def test_auto_submitted_header_skips() -> None:
    ok, reason = is_reply_worthy(_real_email(headers={"Auto-Submitted": "auto-replied"}))
    assert ok is False
    assert reason == "auto_submitted_header"


def test_auto_submitted_no_still_passes() -> None:
    ok, _ = is_reply_worthy(_real_email(headers={"Auto-Submitted": "no"}))
    assert ok is True


def test_list_unsubscribe_header_skips() -> None:
    ok, reason = is_reply_worthy(
        _real_email(headers={"List-Unsubscribe": "<mailto:u@lists.example>"})
    )
    assert ok is False
    assert reason == "list_unsubscribe_header"


def test_precedence_bulk_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(headers={"Precedence": "bulk"}))
    assert ok is False
    assert reason == "bulk_precedence"


def test_precedence_list_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(headers={"precedence": "list"}))
    assert ok is False
    assert reason == "bulk_precedence"


def test_x_failed_recipients_skipped() -> None:
    ok, reason = is_reply_worthy(_real_email(headers={"X-Failed-Recipients": "someone@x.com"}))
    assert ok is False
    assert reason == "bounce_header"


# --- Subject bounce prefixes --------------------------------------------


def test_bounce_subject_delivery_status() -> None:
    ok, reason = is_reply_worthy(_real_email(subject="Delivery Status Notification (Failure)"))
    assert ok is False
    assert reason == "bounce_subject"


def test_bounce_subject_out_of_office() -> None:
    ok, reason = is_reply_worthy(_real_email(subject="Out of Office: back Monday"))
    assert ok is False
    assert reason == "bounce_subject"


def test_bounce_subject_case_insensitive() -> None:
    ok, reason = is_reply_worthy(_real_email(subject="UNDELIVERED MAIL RETURNED"))
    assert ok is False
    assert reason == "bounce_subject"


# --- Body-content checks ------------------------------------------------


def test_body_too_short_skips() -> None:
    # Empty body — no content at all after strip. Short-but-real
    # messages like "thx" / "Hi" / "How are you sir" are legitimate
    # conversational replies and must NOT be rejected here (bumping
    # the threshold to 1 aligns with real inbox behaviour — the noise
    # filters upstream — role account / List-Unsubscribe / bounce /
    # Auto-Submitted — catch the actual auto-mail).
    ok, reason = is_reply_worthy(_real_email(body_text=""))
    assert ok is False
    assert reason == "body_too_short"


def test_body_almost_entirely_quoted_skips() -> None:
    body = (
        "\n\n"
        "On Mon, Aug 20 2025 at 11:42, Jane <j@x.com> wrote:\n"
        "> Hi we have a long previous message here that would blow past\n"
        "> the threshold if we didn't strip it out first...\n"
    )
    ok, reason = is_reply_worthy(_real_email(body_text=body))
    assert ok is False
    assert reason == "body_too_short"


def test_short_real_reply_passes() -> None:
    # Regression guard for the 2026-09-10 threshold change. Short
    # human replies ("thx", "Hii", "How are you sir") were previously
    # rejected as body_too_short at len < 20; the AI is now allowed
    # to answer them since the auto-mail filters upstream already
    # catch the real noise.
    ok, reason = is_reply_worthy(_real_email(body_text="thx"))
    assert ok is True
    assert reason is None


# --- strip_quoted_history helper ----------------------------------------


def test_strip_removes_gt_prefix_lines() -> None:
    body = "Thanks, I'll take three.\n> Original message\n> keeps going\n"
    assert strip_quoted_history(body) == "Thanks, I'll take three."


def test_strip_stops_at_on_wrote_divider() -> None:
    body = (
        "Sounds good.\n\n"
        "On Mon, Aug 20 2025 at 11:42, Jane <j@x.com> wrote:\n"
        "This is the quoted body without gt-prefix in HTML client\n"
    )
    assert strip_quoted_history(body).strip() == "Sounds good."


def test_strip_stops_at_original_message_divider() -> None:
    body = (
        "Here is my reply.\n\n----- Original Message -----\nFrom: previously.said@somewhere.com\n"
    )
    assert strip_quoted_history(body).strip() == "Here is my reply."
