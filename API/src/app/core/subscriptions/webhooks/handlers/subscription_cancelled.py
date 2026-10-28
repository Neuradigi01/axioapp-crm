"""`customer.subscription.deleted` handler.

Stripe sends this event when a subscription reaches its terminal
state (cancelled at period end, immediately cancelled by an
operator, or non-renewable). The local row flips to `cancelled` and
the SubscriptionStateMiddleware (Step 10) blocks subsequent writes.

Idempotent: a redelivery for an already-`cancelled` row is a no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.webhooks.handlers import (
    find_subscription_by_stripe_id,
)

log = logging.getLogger(__name__)


async def on_subscription_cancelled(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
    stripe_sub = event.get("data", {}).get("object", {}) or {}
    stripe_sub_id = stripe_sub.get("id")

    sub = await find_subscription_by_stripe_id(db, stripe_sub_id)
    if sub is None:
        # Cancellation for a subscription we never linked. Likely an
        # operator-side cleanup of a stale Stripe row; nothing to do.
        log.info(
            "customer.subscription.deleted for unlinked sub %s — skipping",
            stripe_sub_id,
        )
        return
    if sub.status == "cancelled":
        # Idempotent path. Our own `POST /subscriptions/cancel` may
        # have flipped the row already; Stripe's event follows.
        return

    now = datetime.now(tz=UTC)
    # Conditional UPDATE so a concurrent operator-side cancel cannot
    # overwrite a different status (e.g. `archived`).
    result = await db.execute(
        update(Subscription)
        .where(
            Subscription.id == sub.id,
            Subscription.status != "cancelled",
        )
        .values(status="cancelled", cancelled_at=now)
    )
    await db.commit()
    if (result.rowcount or 0) == 0:
        return

    await audit.log(
        "subscription.cancelled",
        org_id=sub.org_id,
        entity_type="subscription",
        entity_id=sub.id,
        before={"status": sub.status},
        after={
            "status": "cancelled",
            "cancelled_at": now.isoformat(),
        },
        user_id=None,
    )
    log.info(
        "customer.subscription.deleted → org %s cancelled",
        sub.org_id,
    )
