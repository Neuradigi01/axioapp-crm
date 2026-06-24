"""Campaign send guard
(whatsapp-platform-upgrade Step 22).

Pre-flight opt-in check for every campaign send. Sits between the
contact lookup and the adapter dispatch so an opted-out contact
never receives a marketing template, and an implicit-consent
contact only receives one if the operator explicitly confirms on
the create modal.

Decision shape
--------------

:class:`SendDecision` captures the three outcomes:

  * ``allow``  — proceed with dispatch.
  * ``block``  — refuse the send; mark the row failed with the
    documented reason. The dashboard's failure-reason classifier
    (Step 21) already maps "opted out" → ``opted_out`` bucket.
  * ``warn``   — proceed (or refuse, per the operator's
    confirmation flag passed by the caller). Currently mirrors
    ``allow`` at the API layer; the campaign create modal renders
    a banner UX gated on the same status.

The classifier is deliberately small and pure — it takes a
``Contact`` (any object with the four opt-in attrs) and returns a
decision. No DB / async / side-effects so unit tests can pin every
combination cheaply.

Campaign-category awareness
---------------------------

Marketing templates are the high-stakes case (DPDP fines apply
when an opted-out customer receives one). Utility / authentication
templates and free-text replies in the 24h session window are
considered transactional and bypass the implicit warning — they're
not blocked even for opted-out contacts? **Wrong.** The DPDP /
GDPR rule is broader than just marketing: any opted-out signal
covers ALL outbound. We honour that strictly — opted-out blocks
every category. Operators who need to send a transactional message
must manually re-opt-in the contact first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


SendVerdict = Literal["allow", "warn", "block"]


@dataclass(frozen=True, slots=True)
class SendDecision:
    verdict: SendVerdict
    status: str
    reason: Optional[str]

    @property
    def should_block(self) -> bool:
        return self.verdict == "block"


def evaluate_contact(
    contact: Any,
    *,
    template_category: Optional[str] = None,
    allow_implicit: bool = False,
) -> SendDecision:
    """Decide whether ``contact`` may receive a campaign message.

    Parameters:
      * ``contact`` — any object exposing ``whatsapp_opt_in_status``;
        no DB lookup, no async — the caller already has the row.
      * ``template_category`` — Meta template category (lowercased).
        Reserved for future per-category rules; current logic is
        category-agnostic (opted-out blocks everything).
      * ``allow_implicit`` — operator confirmation flag from the
        campaign create modal. When ``True`` and the contact is
        ``implicit`` consent, we promote ``warn`` → ``allow``.
    """
    status_value = getattr(contact, "whatsapp_opt_in_status", None) or (
        "never_contacted"
    )

    if status_value == "opted_out":
        return SendDecision(
            verdict="block",
            status=status_value,
            reason="contact has opted out of WhatsApp",
        )

    if status_value == "never_contacted":
        # Never sent a customer-initiated message + never explicitly
        # opted in — the safest default is to warn the operator;
        # without explicit allow we block to keep DPDP-conservative.
        if allow_implicit:
            return SendDecision(
                verdict="allow",
                status=status_value,
                reason=None,
            )
        return SendDecision(
            verdict="block",
            status=status_value,
            reason="contact has no opt-in record",
        )

    if status_value == "implicit":
        # Implicit consent — typically pre-DPDP backfilled contacts
        # or first-inbound flips. Send proceeds, but the create
        # modal should have shown a warning banner so the operator
        # consciously chose to dispatch.
        return SendDecision(
            verdict="warn" if not allow_implicit else "allow",
            status=status_value,
            reason=None,
        )

    # opted_in — clean.
    return SendDecision(verdict="allow", status=status_value, reason=None)


def block_reason(decision: SendDecision) -> str:
    """Friendly error string for the failed-message row. Matches
    Step 21's failure classifier so the dashboard bucket is
    correct without a special-case mapping."""
    return (
        decision.reason
        or f"send blocked: contact status={decision.status}"
    )


__all__ = ["SendDecision", "SendVerdict", "block_reason", "evaluate_contact"]
