"""Subscription / plan routes.

Four endpoints live here:

  GET  /api/v1/plans                 — public list (trial excluded)
  GET  /api/v1/plans/{code}          — single plan, includes trial
  GET  /api/v1/subscriptions/current — authenticated, composed read of
                                       the caller's org's subscription
  POST /api/v1/subscriptions/change  — authenticated, request a plan /
                                       cycle / seat change

The first two are unauthenticated — the marketing `/pricing` page and
the signup flow consume them before the visitor is logged in. The
third feeds the in-app billing settings page (Step 16) and the trial
banner (Step 15). The fourth is the Owner-only write path; the
Owner-only gate itself lands in Step 19 via the `billing.manage`
permission key — until then any authenticated org member can call it.
Write paths for seat change and cancellation land in Steps 9 and 10.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import plans, service as subscription_service
from src.app.core.subscriptions.schemas import (
    PlanChangeRequest,
    PlanChangeResponse,
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
