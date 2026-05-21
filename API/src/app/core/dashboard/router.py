"""Dashboard HTTP routes — one endpoint.

`GET /api/v1/dashboard/summary` returns the cards + recent activity +
upcoming appointments for the caller. No permission key required —
every authenticated user gets a dashboard. The response shape adapts
to the caller's permissions inside the service layer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.dashboard.schemas import DashboardSummary
from src.app.core.dashboard.service import get_summary
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary_endpoint(
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    return await get_summary(session, caller)
