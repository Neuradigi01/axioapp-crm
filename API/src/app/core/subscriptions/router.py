"""Subscription / plan routes.

Six endpoints live here:

  GET  /api/v1/plans                          — public list (trial excluded)
  GET  /api/v1/plans/{code}                   — single plan, includes trial
  GET  /api/v1/subscriptions/current          — composed read of the
                                                caller's org's subscription
  POST /api/v1/subscriptions/change           — request a plan / cycle /
                                                seat change
  GET  /api/v1/subscriptions/seats/preview    — see the cost impact of a
                                                proposed seat change
  POST /api/v1/subscriptions/seats            — apply or schedule a seat
                                                change

The first two are unauthenticated — the marketing `/pricing` page and
the signup flow consume them before the visitor is logged in. The rest
require auth; cancellation lands in Step 10. The Owner-only RBAC gate
arrives in Step 19 via the `billing.manage` permission key — until
then any authenticated org member can call the write paths.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import plans, service as subscription_service
from src.app.core.subscriptions.schemas import (
    CancelSubscriptionResponse,
    PlanChangeRequest,
    PlanChangeResponse,
    SeatChangeRequest,
    SeatChangeResponse,
    SeatPreview,
    SubscriptionCurrentResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(tags=["Subscriptions"])


@router.get("/plans")
async def list_public_plans() -> dict:
    return {
        "plans": [p.serialize() for p in plans.public()],
        "currency": plans.currency(),
        "annual_discount_pct": plans.annual_discount_pct(),
    }


@router.get("/plans/{code}")
async def get_plan(code: str) -> dict:
    plan = plans.get(code)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown plan code: {code!r}",
        )
    return plan.serialize()


@router.get(
    "/subscriptions/current",
    response_model=SubscriptionCurrentResponse,
)
async def get_current_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionCurrentResponse:
    """Return the caller's org's active subscription with plan + usage.

    Read is open to any authenticated user in the org — managing the
    plan / seats / cancellation lives behind the Owner role gate in
    Steps 8-10 (RBAC keys registered in Step 19).
    """
    return await subscription_service.compose_current_subscription_response(
        db, user.org_id
    )


@router.post(
    "/subscriptions/change",
    response_model=PlanChangeResponse,
)
async def change_subscription(
    payload: PlanChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request a plan / billing-cycle / seat change for the caller's org.

    Returns one of three discriminated-union shapes — `no_change`,
    `needs_payment`, or `scheduled` — selected by the service. 4xx
    detail bodies use the structured `{"error": "<code>", ...}`
    shape so the frontend can decode them without parsing strings.

    The Owner-only RBAC gate is added in Step 19; for now any
    authenticated org member can call this endpoint. Read-only and
    archived subs DELIBERATELY pass auth here — this is the recovery
    path the trial-ended banner links to.
    """
    return await subscription_service.change_plan(
        db,
        user.org_id,
        to_plan=payload.to_plan,
        billing_cycle=payload.billing_cycle,
        seats=payload.seats,
    )


@router.get(
    "/subscriptions/seats/preview",
    response_model=SeatPreview,
)
async def preview_seat_change(
    total_seats: int = Query(..., ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SeatPreview:
    """Read-only cost projection for the seat-management modal.

    Does not commit anything; the UI calls this on input change and
    renders `amount_due_usd` + the projected per-cycle cost. The
    commit path (POST) does its own validation and may reject the
    request, so `outcome_if_committed` is informational, not a
    promise.
    """
    return await subscription_service.preview_seat_change(
        db, user.org_id, total_seats
    )


@router.post(
    "/subscriptions/seats",
    response_model=SeatChangeResponse,
)
async def change_seats(
    payload: SeatChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply or schedule a seat-count change.

    `total_seats` is the desired *total*, not a delta. Adding seats
    on a paid plan returns `needs_payment` (Step 12 fills the
    `checkout_url`); removing seats schedules at the next period
    boundary; no_change returns immediately. Trial subs cannot add
    seats (use upgrade instead).
    """
    return await subscription_service.change_seats(
        db, user.org_id, total_seats=payload.total_seats,
    )


@router.post(
    "/subscriptions/cancel",
    response_model=CancelSubscriptionResponse,
)
async def cancel_subscription_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelSubscriptionResponse:
    """Mark the caller's org subscription cancelled.

    Idempotent — calling twice returns the same `cancelled_at` with
    `already_cancelled=true`. The local row flip is enough to revoke
    write access via the SubscriptionStateMiddleware; the Stripe-side
    sub is cancelled by Step 13's webhook.

    Owner-only RBAC arrives in Step 19 (`billing.manage` permission
    key); for now any authenticated org member can call it. The
    middleware passes this path through even on already-cancelled subs
    so the idempotent contract holds end-to-end.
    """
    return await subscription_service.cancel_subscription(
        db, user.org_id,
    )
