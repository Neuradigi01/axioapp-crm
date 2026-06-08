"""Subscription / plan routes.

Three endpoints live here:

  GET /api/v1/plans                 — public list (trial excluded)
  GET /api/v1/plans/{code}          — single plan, includes trial
  GET /api/v1/subscriptions/current — authenticated, composed read of
                                      the caller's org's subscription

The first two are unauthenticated — the marketing `/pricing` page and
the signup flow consume them before the visitor is logged in. The
third feeds the in-app billing settings page (Step 16) and the trial
banner (Step 15); only authenticated users see it. Write paths (plan
change, seat change, cancellation) land in Steps 8-10 and gate on
the Owner role (Step 19).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.subscriptions import plans, service as subscription_service
from src.app.core.subscriptions.schemas import SubscriptionCurrentResponse
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
