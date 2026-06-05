"""Subscription service — read helpers used by downstream billing code.

This step delivers only `get_active_subscription`. Write paths land in
later steps:
  - Step 6: `create_trial_subscription` (signup hook)
  - Step 8: `change_plan`
  - Step 9: `change_seats`
  - Step 10: `cancel_subscription`

Reads are scoped by the active org via the `TenantScoped` ORM mixin
(see `shared/orm.py`) and Postgres RLS — the service does NOT add an
explicit `org_id = ?` predicate because the loader already does it.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.models import ACTIVE_STATUSES, Subscription


async def get_active_subscription(
    session: AsyncSession, org_id: uuid.UUID
) -> Subscription | None:
    """Return the org's currently-active subscription, or None.

    "Active" here means `status` is one of `(trialing, active, past_due,
    read_only)` — the same set the partial unique index enforces. Rows
    in `archived` or `cancelled` are history and ignored.

    The `org_id` argument is required even though `TenantScoped` would
    auto-filter on a context-bound session: callers in background tasks
    (Step 6 lifecycle, Step 13 webhooks) may have no request context.
    Passing the id explicitly makes both call shapes work.
    """
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
