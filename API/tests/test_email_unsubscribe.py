"""Campaigns v1 Step 06 — Email opt-in send guard.

Focused unit tests on ``evaluate_email_contact`` — the compliance
boundary that keeps unsubscribed contacts out of every future
dispatch. Uses Contact-shaped stand-ins so the whole file runs without
a DB round-trip (per repo memory pytest runs ~12 min against the real
DB).

End-to-end coverage of the tracking unsub endpoint's DB flip lands
with the browser smoke on Ajay's Workspace (send yourself an email,
click Unsubscribe, verify the tri-state flips to ``opted_out``).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.app.core.campaigns.send_guard import (
    block_reason,
    evaluate_email_contact,
)


@dataclass
class _Contact:
    email: str | None = "aditi@example.com"
    email_opt_out: bool = False
    email_opt_in_status: str | None = "never_contacted"


class TestEvaluateEmailContact:
    def test_opted_out_blocks_even_when_allow_implicit(self):
        contact = _Contact(email_opt_in_status="opted_out")
        decision = evaluate_email_contact(contact, allow_implicit=True)
        assert decision.verdict == "block"
        assert "opted out" in decision.reason.lower()
        assert "Email" in decision.reason

    def test_legacy_email_opt_out_bool_blocks(self):
        # Even if a legacy row somehow escaped the migration backfill,
        # the boolean shortcut catches it.
        contact = _Contact(email_opt_out=True, email_opt_in_status="never_contacted")
        decision = evaluate_email_contact(contact, allow_implicit=True)
        assert decision.verdict == "block"

    def test_never_contacted_blocks_without_allow_implicit(self):
        contact = _Contact(email_opt_in_status="never_contacted")
        decision = evaluate_email_contact(contact, allow_implicit=False)
        assert decision.verdict == "block"
        assert "no Email opt-in record" in decision.reason

    def test_never_contacted_allowed_with_allow_implicit(self):
        contact = _Contact(email_opt_in_status="never_contacted")
        decision = evaluate_email_contact(contact, allow_implicit=True)
        assert decision.verdict == "allow"
        assert decision.reason is None

    def test_implicit_warns_when_allow_implicit_false(self):
        contact = _Contact(email_opt_in_status="implicit")
        decision = evaluate_email_contact(contact, allow_implicit=False)
        assert decision.verdict == "warn"

    def test_implicit_allowed_with_allow_implicit(self):
        contact = _Contact(email_opt_in_status="implicit")
        decision = evaluate_email_contact(contact, allow_implicit=True)
        assert decision.verdict == "allow"

    def test_opted_in_always_allows(self):
        contact = _Contact(email_opt_in_status="opted_in")
        for allow in (True, False):
            decision = evaluate_email_contact(contact, allow_implicit=allow)
            assert decision.verdict == "allow"

    def test_missing_status_attribute_treated_as_never_contacted(self):
        # A DB row loaded before the migration ran would lack the
        # attribute entirely. Getattr fallback keeps dispatch safe.
        @dataclass
        class _BareContact:
            email: str | None = "x@example.com"
            email_opt_out: bool = False

        decision = evaluate_email_contact(_BareContact(), allow_implicit=False)
        assert decision.verdict == "block"
        assert "no Email opt-in record" in decision.reason

    def test_block_reason_helper(self):
        contact = _Contact(email_opt_in_status="opted_out")
        decision = evaluate_email_contact(contact)
        assert "opted out" in block_reason(decision).lower()

    def test_wa_and_email_guards_are_independent(self):
        # A contact who opted out of Email but is opted-in on WhatsApp
        # is only blocked on the Email side. Regression-guards the
        # cross-channel independence.
        from src.app.core.campaigns.send_guard import evaluate_contact

        @dataclass
        class _MixedContact:
            email: str | None = "y@example.com"
            email_opt_out: bool = True
            email_opt_in_status: str = "opted_out"
            whatsapp_opt_in_status: str = "opted_in"

        email_decision = evaluate_email_contact(
            _MixedContact(), allow_implicit=False
        )
        wa_decision = evaluate_contact(_MixedContact(), allow_implicit=False)
        assert email_decision.verdict == "block"
        assert wa_decision.verdict == "allow"
