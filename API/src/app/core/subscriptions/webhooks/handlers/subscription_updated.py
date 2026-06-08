"""`customer.subscription.updated` handler.

Syncs seat / plan / cycle changes that an operator made directly in
the Stripe Dashboard back into our row. The handler diffs the
incoming `data.object` against the local row and writes only the
differing fields, so a redelivered event with the same state is a
no-op rather than a wasted UPDATE.

We *do not* update the status from this event — Stripe's
`customer.subscription.deleted` is the canonical cancellation
signal, and `invoice.payment_failed` is the past_due signal. Mixing
status changes here would race the dedicated handlers.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.webhooks.handlers import (
    find_subscription_by_stripe_id,
)

log = logging.getLogger(__name__)


async def on_subscription_updated(
    db: AsyncSession, event: dict[str, Any],
) -> None:
    stripe_sub = event.get("data", {}).get("object", {}) or {}
    stripe_sub_id = stripe_sub.get("id")

    sub = await find_subscription_by_stripe_id(db, stripe_sub_id)
    if sub is None:
        # Stripe sometimes emits update events for subscriptions we
        # never linked (e.g. operator-created subs that haven't been
        # imported). Silently ignore — the dedup ledger still marks
        # the event processed so Stripe stops retrying.
        log.info(
            "customer.subscription.updated for unlinked sub %s — skipping",
            stripe_sub_id,
        )
        return

    items = (stripe_sub.get("items") or {}).get("data") or []
    if not items:
        return
    item = items[0]
    new_quantity = item.get("quantity")
    price = item.get("price") or {}
    price_metadata = price.get("metadata") or {}
    new_plan_code = price_metadata.get("plan_code")
    new_billing_cycle = price_metadata.get("billing_cycle")

    changes: dict[str, Any] = {}
    if (
        isinstance(new_quantity, int)
        and new_quantity > 0
        and new_quantity != sub.seats_purchased
    ):
        changes["seats_purchased"] = new_quantity
    if new_plan_code and new_plan_code != sub.plan_code:
        changes["plan_code"] = new_plan_code
    if new_billing_cycle and new_billing_cycle != sub.billing_cycle:
        changes["billing_cycle"] = new_billing_cycle

    if not changes:
        return

    before = {k: getattr(sub, k) for k in changes}

    await db.execute(
        update(Subscription).where(Subscription.id == sub.id).values(**changes)
    )
    await db.commit()

    await audit.log(
        "subscription.synced_from_stripe",
        org_id=sub.org_id,
        entity_type="subscription",
        entity_id=sub.id,
        before=before,
        after=changes,
        user_id=None,
    )
    log.info(
        "customer.subscription.updated → org %s applied %s",
        sub.org_id, changes,
    )
