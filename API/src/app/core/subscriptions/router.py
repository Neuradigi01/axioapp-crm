"""Public plan-catalog routes.

Two endpoints, both unauthenticated — the marketing `/pricing` page
and the signup flow consume them before the visitor is logged in.

  GET /api/v1/plans          — list of public plans (trial excluded)
  GET /api/v1/plans/{code}   — one plan, including the non-public trial
                               (used internally by the signup hook)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.app.core.subscriptions import plans


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
