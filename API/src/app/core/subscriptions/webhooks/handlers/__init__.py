"""Stripe webhook handlers — sub-step 13.b.

Each module here implements one handler for a Stripe event type. The
router's `_HANDLERS` dispatch table imports from them; the router
itself remains a thin frame (verify, dedup, dispatch).

Shared helpers — `find_subscription_by_stripe_id` and
`parse_unix_ts` — live here so the per-handler modules stay focused
on event-specific logic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.models import Subscription


async def find_subscription_by_stripe_id(
    db: AsyncSession, stripe_subscription_id: str,
) -> Subscription | None:
    """Lookup a local subscription by its Stripe-side ID.

    Returns `None` if no row matches — the calling handler decides
    whether that's an error (raise → 500 → Stripe retries) or a
    benign no-op (skip silently for out-of-order events).
    """
    if not stripe_subscription_id:
        return None
    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
    )
    return result.scalar_one_or_none()


def parse_unix_ts(value: int | float | None) -> datetime | None:
    """Convert a Stripe-style Unix timestamp to a UTC `datetime`.

    Stripe emits seconds-since-epoch as an integer; absent fields are
    `None`. Returning `None` for `None` lets the handler pass an
    optional-typed column straight through without a conditional.
    """
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
