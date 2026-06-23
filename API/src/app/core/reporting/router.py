"""HTTP routes for the reporting module.

  GET /api/v1/reports/workload?active_only=true
  GET /api/v1/reports/whatsapp/volume
  GET /api/v1/reports/whatsapp/response-time
  GET /api/v1/reports/whatsapp/outcomes
  GET /api/v1/reports/whatsapp/agent-leaderboard

`/workload` is gated on `users.read`. The WhatsApp surfaces sit
behind a dedicated `whatsapp.analytics.read` permission
(whatsapp-platform-upgrade Step 20) — Owner + Admin get it by
default; Sales-Junior does not, so the dashboard tab hides via the
module registry.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.reporting.service import compute_workload
from src.app.core.reporting.whatsapp_analytics import (
    compute_agent_leaderboard,
    compute_outcomes,
    compute_response_time,
    compute_volume,
)
from src.app.core.users.models import User
from src.app.core.users.schemas import (
    OpenRecordsCounts,
    WorkloadEntry,
    WorkloadReport,
)
from src.app.shared.db import get_db


router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/workload", response_model=WorkloadReport)
async def workload_endpoint(
    active_only: bool = Query(default=True),
    user: User = Depends(require_permissions("users.read")),
    session: AsyncSession = Depends(get_db),
) -> WorkloadReport:
    """Per-user open-record counts across the org. Drives the
    Settings → Staff Workload tab plus optional list-page widgets."""
    summary = await compute_workload(
        session, org_id=user.org_id, active_only=active_only
    )
    entries = [
        WorkloadEntry(
            user_id=row["user_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_active=row["is_active"],
            counts=OpenRecordsCounts(**row["counts"]),
        )
        for row in summary["users"]
    ]
    return WorkloadReport(users=entries, as_of=summary["as_of"])


# --- WhatsApp analytics (whatsapp-platform-upgrade Step 20) -----------------


_RANGE_QUERY = Query(default="7d", pattern="^(7d|30d|90d)$")
_GRANULARITY_QUERY = Query(default="day", pattern="^(day|hour)$")


class _VolumeBucketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bucket_start: datetime
    sent: int
    received: int
    failed: int
    ai_sent: int


class _VolumeReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    granularity: str
    buckets: list[_VolumeBucketOut]
    total_sent: int
    total_received: int
    total_failed: int
    total_ai_sent: int


class _ResponseTimeBucketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    label: str
    seconds_lt: int
    count: int


class _ResponseTimeGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    median_seconds: Optional[float]
    p95_seconds: Optional[float]
    sample_size: int


class _ResponseTimeReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    groupby: str
    overall_median_seconds: Optional[float]
    overall_p95_seconds: Optional[float]
    sample_size: int
    distribution: list[_ResponseTimeBucketOut]
    groups: list[_ResponseTimeGroupOut]


class _OutcomeSliceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    count: int


class _OutcomesReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    by_status: list[_OutcomeSliceOut]
    by_tag: list[_OutcomeSliceOut]
    total: int


class _LeaderboardRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: uuid.UUID
    name: str
    replies: int
    conversations_handled: int
    median_response_seconds: Optional[float]
    p95_response_seconds: Optional[float]


class _LeaderboardReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    rows: list[_LeaderboardRowOut]


@router.get(
    "/whatsapp/volume",
    response_model=_VolumeReportOut,
    summary="WhatsApp message volume — sent / received / failed buckets",
)
async def whatsapp_volume_endpoint(
    range: str = _RANGE_QUERY,
    granularity: str = _GRANULARITY_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _VolumeReportOut:
    try:
        report = await compute_volume(
            session,
            org_id=user.org_id,
            range_key=range,
            granularity=granularity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return _VolumeReportOut.model_validate(report)


@router.get(
    "/whatsapp/response-time",
    response_model=_ResponseTimeReportOut,
    summary="WhatsApp first-staff-reply latency — median, p95, histogram",
)
async def whatsapp_response_time_endpoint(
    range: str = _RANGE_QUERY,
    groupby: Literal["agent", "team", "channel"] = Query(default="agent"),
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _ResponseTimeReportOut:
    try:
        report = await compute_response_time(
            session,
            org_id=user.org_id,
            range_key=range,
            groupby=groupby,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return _ResponseTimeReportOut.model_validate(report)


@router.get(
    "/whatsapp/outcomes",
    response_model=_OutcomesReportOut,
    summary="WhatsApp conversation status distribution + tag breakdown",
)
async def whatsapp_outcomes_endpoint(
    range: str = _RANGE_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _OutcomesReportOut:
    try:
        report = await compute_outcomes(
            session, org_id=user.org_id, range_key=range
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return _OutcomesReportOut.model_validate(report)


@router.get(
    "/whatsapp/agent-leaderboard",
    response_model=_LeaderboardReportOut,
    summary="Per-agent reply count + response-time percentiles",
)
async def whatsapp_agent_leaderboard_endpoint(
    range: str = _RANGE_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _LeaderboardReportOut:
    try:
        report = await compute_agent_leaderboard(
            session, org_id=user.org_id, range_key=range
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return _LeaderboardReportOut.model_validate(report)
