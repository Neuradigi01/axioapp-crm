"""Dashboard HTTP routes.

`GET /api/v1/dashboard/summary` returns the cards + recent activity +
upcoming appointments for the caller.

`GET /api/v1/dashboard/trend` returns a day-bucketed time series for a
chosen metric over a chosen range — powers the trend chart widget.

Neither endpoint requires a permission key — every authenticated user
gets a dashboard. The response shape adapts to the caller's permissions
inside the service layer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.dashboard.schemas import (
    DashboardSummary,
    DashboardTrendResponse,
    TrendMetric,
    TrendRange,
)
from src.app.core.dashboard.service import assemble_trend, get_summary
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary_endpoint(
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    return await get_summary(session, caller)


@router.get("/trend", response_model=DashboardTrendResponse)
async def trend_endpoint(
    metric: TrendMetric = Query("leads_created"),
    range: TrendRange = Query("30d"),
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardTrendResponse:
    return await assemble_trend(session, caller, metric, range)
