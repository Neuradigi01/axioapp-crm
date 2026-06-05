"""Stub for outbound billing emails.

Step 20 replaces this module with the real implementation: Jinja2
template rendering, Owner resolution, Celery dispatch to the existing
`core.notifications` SMTP backend.

For now (Steps 6 - 19) every emit-site calls `send_billing_email(...)`
which logs the intent and returns. This lets the rest of the billing
track wire its emit calls today without blocking on the email
template work.

The keyset is fixed so downstream code only uses known reminder
identifiers; adding a new email key requires updating both the
emit-site and Step 20's template registry.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

log = logging.getLogger(__name__)


BillingEmailKey = Literal[
    "trial_ending_soon",
    "trial_expired",
    "subscription_archived",
    "payment_succeeded",
    "payment_failed",
    "seats_added",
    "plan_changed",
]


async def send_billing_email(
    *,
    org_id: uuid.UUID,
    template_key: BillingEmailKey,
    context: dict[str, Any] | None = None,
) -> None:
    """Queue a billing email for the org's Owner.

    Stub: emits a structured log line ("billing_email.queued") so the
    trial-lifecycle smoke shows the right side-effects landed even
    before the real SMTP plumbing exists. Step 20 swaps this for the
    real implementation.

    Best-effort by contract — never raises. If the caller's parent
    flow is mid-transaction, a delivery hiccup must not 5xx the
    user-visible response.
    """
    log.info(
        "billing_email.queued org_id=%s template=%s context=%s",
        org_id,
        template_key,
        context or {},
    )
