"""Subscription service — read helpers used by downstream billing code.

This step delivers `get_active_subscription` plus the composed read used
by `GET /api/v1/subscriptions/current` (Step 7). Write paths land in
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

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions import plans
from src.app.core.subscriptions.models import ACTIVE_STATUSES, Subscription
from src.app.core.subscriptions.schemas import SubscriptionCurrentResponse
from src.app.core.users.service import count_active_members


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


async def compose_current_subscription_response(
    session: AsyncSession, org_id: uuid.UUID
) -> SubscriptionCurrentResponse:
    """Compose the read response for `GET /api/v1/subscriptions/current`.

    Folds together the four facets the billing page needs:
      1. the active subscription row,
      2. its plan from the registry,
      3. the count of active org members (= `seats.in_use`),
      4. the metered-resource usage snapshot.

    Raises 404 when no active subscription exists — the frontend treats
    that as "needs to pick a plan." Post the Step 2 backfill this should
    not happen for a real org, but the endpoint is defensive.

    A subscription pointing at a plan code the YAML registry no longer
    carries is a hard data error and raises ``RuntimeError`` — mirrors
    the entitlement service's behaviour on the same condition so the
    surfaces are consistent.
    """
    # Local import: `usage_service` imports `get_active_subscription`
    # from this module, so a top-level import would deadlock the loader.
    from src.app.core.subscriptions import usage_service
    from src.app.core.subscriptions.usage_service import RESOURCE_PERIOD_KIND

    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription",
        )
    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(
            f"subscription {sub.id} references unknown plan {sub.plan_code!r}"
        )
    seats_in_use = await count_active_members(session, org_id)
    usage_snap = await usage_service.snapshot(
        session, org_id, list(RESOURCE_PERIOD_KIND.keys())
    )
    return SubscriptionCurrentResponse.from_components(
        sub=sub,
        plan=plan,
        seats_in_use=seats_in_use,
        usage_snapshot=usage_snap,
    )
