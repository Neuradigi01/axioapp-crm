"""Dashboard HTTP routes.

`GET /api/v1/dashboard/summary` returns the cards + recent activity +
upcoming appointments for the caller.

`GET /api/v1/dashboard/trend` returns a day-bucketed time series for a
chosen metric over a chosen range — powers the trend chart widget.

`GET /api/v1/dashboard/funnel` returns lead counts per pipeline stage
over a chosen range — powers the funnel chart widget.

None of these endpoints require a permission key — every authenticated
user gets a dashboard. The response shape adapts to the caller's
permissions inside the service layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.dashboard.schemas import (
    DashboardFunnelResponse,
    DashboardSummary,
    DashboardTrendResponse,
    TrendMetric,
    TrendRange,
)
from src.app.core.dashboard.service import (
    assemble_funnel,
    assemble_trend,
    get_summary,
)
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


@router.get("/funnel", response_model=DashboardFunnelResponse)
async def funnel_endpoint(
    range: TrendRange = Query("30d"),
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardFunnelResponse:
    return await assemble_funnel(session, caller, range)
