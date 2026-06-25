"""Data-access layer for the subscriptions module.

Pure query helpers — no transactions, no audit, no plan-registry
lookup, no Stripe calls. Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Subscriptions (``tbl_subscriptions``)
      get_active_subscription_for_org, get_latest_subscription_for_org,
      get_subscription_by_id,
      update_subscription_next_plan_fields,
      update_subscription_next_seats,
      update_subscription_cancelled_conditional,
      update_subscription_stripe_customer_conditional,
      update_subscription_pending_checkout
  * Subscription invoices (``tbl_subscription_invoices``)
      list_invoices_for_org
  * Usage counters (``tbl_usage_counters``) — meterable resources
      get_usage_counter_value, upsert_usage_counter_returning,
      insert_zero_counter_if_absent
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.models import (
    ACTIVE_STATUSES,
    Subscription,
    SubscriptionInvoice,
    UsageCounter,
)


# --- Subscriptions ------------------------------------------------------


async def get_active_subscription_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> Optional[Subscription]:
    """Return the org's currently-active subscription, or ``None``.
    ``Active`` means ``status IN ACTIVE_STATUSES`` — the same set the
    partial unique index enforces."""
    stmt = (
        select(Subscription)
        .where(
            Subscription.org_id == org_id,
            Subscription.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_subscription_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> Optional[Subscription]:
    """Most-recent subscription row regardless of status. Used by the
    cancellation idempotent path which needs to see a ``cancelled``
    row to short-circuit."""
    return (
        await session.execute(
            select(Subscription)
            .where(Subscription.org_id == org_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_subscription_by_id(
    session: AsyncSession, sub_id: uuid.UUID
) -> Optional[Subscription]:
    """Single-row read by PK. Used by the race-loss re-read paths
    after a conditional UPDATE fails to touch any row."""
    return (
        await session.execute(
            select(Subscription).where(Subscription.id == sub_id)
        )
    ).scalar_one_or_none()


async def update_subscription_next_plan_fields(
    session: AsyncSession,
    *,
    sub_id: uuid.UUID,
    next_plan_code: str,
    next_billing_cycle: str,
    next_seats: int,
) -> None:
    """UPDATE ``next_plan_code`` + ``next_billing_cycle`` +
    ``next_seats`` on one subscription row. Caller commits. Used by
    the "scheduled" outcome of the plan-change flow."""
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub_id)
        .values(
            next_plan_code=next_plan_code,
            next_billing_cycle=next_billing_cycle,
            next_seats=next_seats,
        )
    )


async def update_subscription_next_seats(
    session: AsyncSession,
    *,
    sub_id: uuid.UUID,
    next_seats: int,
) -> None:
    """UPDATE only ``next_seats`` on one subscription row. Used by
    the seat-change scheduled path."""
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub_id)
        .values(next_seats=next_seats)
    )


async def update_subscription_cancelled_conditional(
    session: AsyncSession,
    *,
    sub_id: uuid.UUID,
    when: datetime,
) -> int:
    """Conditional UPDATE that flips ``status='cancelled'`` +
    ``cancelled_at=when`` only when the row isn't already cancelled.
    Returns the affected rowcount so the caller can detect a lost
    race with a concurrent webhook."""
    result = await session.execute(
        update(Subscription)
        .where(
            Subscription.id == sub_id,
            Subscription.status != "cancelled",
        )
        .values(status="cancelled", cancelled_at=when)
    )
    return int(result.rowcount or 0)


async def update_subscription_stripe_customer_conditional(
    session: AsyncSession,
    *,
    sub_id: uuid.UUID,
    customer_id: str,
) -> int:
    """Conditional UPDATE that sets ``stripe_customer_id`` only when
    the column is still NULL. Returns the affected rowcount so the
    caller can detect a lost race with a concurrent webhook fill-in."""
    result = await session.execute(
        update(Subscription)
        .where(
            Subscription.id == sub_id,
            Subscription.stripe_customer_id.is_(None),
        )
        .values(stripe_customer_id=customer_id)
    )
    return int(result.rowcount or 0)


async def update_subscription_pending_checkout(
    session: AsyncSession,
    *,
    sub_id: uuid.UUID,
    session_id: str,
) -> None:
    """UPDATE ``pending_checkout_session_id`` on one subscription row.
    Step 13's Stripe webhook later correlates this id back to the
    fulfilment event."""
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub_id)
        .values(pending_checkout_session_id=session_id)
    )


# --- Subscription invoices ----------------------------------------------


async def list_invoices_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> list[SubscriptionInvoice]:
    """All Stripe invoices mirrored for ``org_id``, newest first.
    Explicit ``org_id`` predicate + the ``TenantScoped`` listener
    together belt-and-suspenders the tenant scoping."""
    rows = (
        await session.execute(
            select(SubscriptionInvoice)
            .where(SubscriptionInvoice.org_id == org_id)
            .order_by(SubscriptionInvoice.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


# --- Usage counters -----------------------------------------------------


# Raw upsert + RETURNING used by ``upsert_usage_counter_returning`` —
# kept as a single ``text()`` statement so the parameterised
# ``EXCLUDED.value`` semantics survive intact.
_UPSERT_USAGE_SQL = text(
    """
    INSERT INTO tbl_usage_counters (
        org_id, resource, period_kind, period_start, period_end, value, updated_at
    )
    VALUES (:org_id, :resource, :period_kind, :period_start, :period_end, :delta, now())
    ON CONFLICT (org_id, resource, period_start)
    DO UPDATE SET value = tbl_usage_counters.value + EXCLUDED.value, updated_at = now()
    RETURNING value
    """
)


# Raw insert used by the period-rollover paths. Idempotent via
# ``ON CONFLICT DO NOTHING``; same unique index as the upsert.
_INSERT_ZERO_COUNTER_SQL = text(
    """
    INSERT INTO tbl_usage_counters (
        org_id, resource, period_kind, period_start, period_end, value, updated_at
    )
    VALUES (:org_id, :resource, :period_kind, :period_start, :period_end, 0, now())
    ON CONFLICT (org_id, resource, period_start) DO NOTHING
    """
)


async def get_usage_counter_value(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    resource: str,
    period_start: datetime,
) -> Optional[int]:
    """Read one counter's ``value`` for the specified period. ``None``
    if no row exists yet (caller defaults to 0)."""
    row = (
        await session.execute(
            select(UsageCounter.value).where(
                UsageCounter.org_id == org_id,
                UsageCounter.resource == resource,
                UsageCounter.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    return None if row is None else int(row)


async def upsert_usage_counter_returning(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    resource: str,
    period_kind: str,
    period_start: datetime,
    period_end: datetime,
    delta: int,
) -> int:
    """Atomically bump the current-period counter by ``delta`` and
    return the new value.

    Race-safe: the underlying ``INSERT ... ON CONFLICT DO UPDATE``
    serialises concurrent bumps via the
    ``(org_id, resource, period_start)`` unique index. Negative
    ``delta`` is allowed for decrements (e.g., a contact is deleted)
    — the value is intentionally not floored at 0 because going
    transiently negative is informative when reconciling drift.

    Caller's session manages the transaction (no commit here)."""
    result = await session.execute(
        _UPSERT_USAGE_SQL,
        {
            "org_id": org_id,
            "resource": resource,
            "period_kind": period_kind,
            "period_start": period_start,
            "period_end": period_end,
            "delta": delta,
        },
    )
    return int(result.scalar_one())


async def insert_zero_counter_if_absent(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    resource: str,
    period_kind: str,
    period_start: datetime,
    period_end: datetime,
) -> int:
    """Idempotent INSERT of a zero-valued counter for the new period.
    Returns 1 when a fresh row landed, 0 when the row already existed
    (``ON CONFLICT DO NOTHING``). Used by the monthly + daily
    rollover tasks."""
    result = await session.execute(
        _INSERT_ZERO_COUNTER_SQL,
        {
            "org_id": org_id,
            "resource": resource,
            "period_kind": period_kind,
            "period_start": period_start,
            "period_end": period_end,
        },
    )
    return int(result.rowcount or 0)


__all__ = [
    "get_active_subscription_for_org",
    "get_latest_subscription_for_org",
    "get_subscription_by_id",
    "get_usage_counter_value",
    "insert_zero_counter_if_absent",
    "list_invoices_for_org",
    "update_subscription_cancelled_conditional",
    "update_subscription_next_plan_fields",
    "update_subscription_next_seats",
    "update_subscription_pending_checkout",
    "update_subscription_stripe_customer_conditional",
    "upsert_usage_counter_returning",
]
