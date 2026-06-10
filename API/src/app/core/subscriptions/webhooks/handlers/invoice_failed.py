"""`invoice.payment_failed` handler.

Mirrors the failed invoice into `subscription_invoices` with
`status='open'` (Stripe will keep retrying the charge) and flips the
local subscription from `active` to `past_due`. The
SubscriptionStateMiddleware (Step 10) then blocks writes until the
customer fixes their payment method and `invoice.paid` arrives.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.notifications import send_billing_email
from src.app.core.subscriptions.webhooks.handlers.invoice_paid import (
    _upsert_invoice,
)

log = logging.getLogger(__name__)


async def on_invoice_failed(
    db: AsyncSession, event: dict[str, Any],
) -> None:
    invoice = event.get("data", {}).get("object", {}) or {}
    sub = await _upsert_invoice(db, invoice, force_status="open")
    if sub is None:
        return

    # Only flip `active` → `past_due`; never demote `trialing`,
    # `read_only`, etc. The conditional UPDATE encodes that constraint
    # so a race with another webhook can't downgrade the status.
    result = await db.execute(
        update(Subscription)
        .where(
            Subscription.id == sub.id,
            Subscription.status == "active",
        )
        .values(status="past_due")
    )
    await db.commit()
    if (result.rowcount or 0) > 0:
        await audit.log(
            "payment.failed",
            org_id=sub.org_id,
            entity_type="subscription",
            entity_id=sub.id,
            before={"status": "active"},
            after={"status": "past_due"},
            user_id=None,
        )
        log.info(
            "invoice.payment_failed → org %s flipped to past_due",
            sub.org_id,
        )

    # Step 20 — best-effort email regardless of whether the status
    # actually flipped: customer needs to know their card was declined
    # even if the sub was already in `past_due` from an earlier event.
    await send_billing_email(
        org_id=sub.org_id,
        template_key="payment_failed",
        context={},
    )
