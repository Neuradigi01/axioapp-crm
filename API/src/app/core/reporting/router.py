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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.reporting.ad_attribution import compute_ad_attribution
from src.app.core.reporting.campaign_analytics import (
    compute_ab_comparison,
    compute_ai_metrics,
    compute_campaign_failures,
    compute_campaign_funnel,
    compute_cost,
    compute_quality_timeline,
)
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
    summary = await compute_workload(session, org_id=user.org_id, active_only=active_only)
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
    median_seconds: float | None
    p95_seconds: float | None
    sample_size: int


class _ResponseTimeReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    groupby: str
    overall_median_seconds: float | None
    overall_p95_seconds: float | None
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
    median_response_seconds: float | None
    p95_response_seconds: float | None


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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
        report = await compute_outcomes(session, org_id=user.org_id, range_key=range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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
        report = await compute_agent_leaderboard(session, org_id=user.org_id, range_key=range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _LeaderboardReportOut.model_validate(report)


# --- Campaign + cost + quality + AI metrics (Step 21) ----------------------


class _FunnelStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    count: int


class _CampaignFunnelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: uuid.UUID
    name: str
    status: str
    started_at: datetime | None
    stages: list[_FunnelStageOut]
    delivery_median_seconds: float | None
    delivery_p95_seconds: float | None


class _FailureBucketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    reason: str
    label: str
    count: int


class _CampaignFailuresOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: uuid.UUID
    total_failed: int
    buckets: list[_FailureBucketOut]
    sample_errors: list[str]


class _CostLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    category: str
    count: int
    rate: float
    currency: str
    total: float


class _CostReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    region: str
    currency: str
    lines: list[_CostLineOut]
    total: float
    is_estimate: bool


class _QualityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    occurred_at: datetime
    event_type: str
    old_value: str | None
    new_value: str | None


class _QualityVolumePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bucket_start: datetime
    sent: int


class _QualityTimelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    events: list[_QualityEventOut]
    volume: list[_QualityVolumePointOut]


class _AIMetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    ai_replies: int
    human_replies: int
    ai_response_rate: float
    ai_handled_conversations: int
    escalated_conversations: int
    escalation_rate: float
    ai_only_completed: int
    escalation_reasons: dict[str, int]


_REGION_QUERY = Query(default="IN", pattern="^[A-Z]{2}$")
_RANGE30_QUERY = Query(default="30d", pattern="^(7d|30d|90d)$")


@router.get(
    "/campaigns/{campaign_id}/funnel",
    response_model=_CampaignFunnelOut,
    summary="Per-campaign funnel (targeted → sent → … → converted)",
)
async def campaign_funnel_endpoint(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _CampaignFunnelOut:
    report = await compute_campaign_funnel(session, org_id=user.org_id, campaign_id=campaign_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="campaign not found",
        )
    return _CampaignFunnelOut.model_validate(report)


@router.get(
    "/campaigns/{campaign_id}/failures",
    response_model=_CampaignFailuresOut,
    summary="Per-campaign failure breakdown by reason taxonomy",
)
async def campaign_failures_endpoint(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _CampaignFailuresOut:
    report = await compute_campaign_failures(session, org_id=user.org_id, campaign_id=campaign_id)
    return _CampaignFailuresOut.model_validate(report)


@router.get(
    "/whatsapp/cost",
    response_model=_CostReportOut,
    summary="Estimated WhatsApp cost (Meta categories × region rates)",
)
async def whatsapp_cost_endpoint(
    range: str = _RANGE30_QUERY,
    region: str = _REGION_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _CostReportOut:
    try:
        report = await compute_cost(
            session,
            org_id=user.org_id,
            region=region,
            range_key=range,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _CostReportOut.model_validate(report)


@router.get(
    "/whatsapp/quality-timeline",
    response_model=_QualityTimelineOut,
    summary="Phone-quality events + daily send volume",
)
async def whatsapp_quality_timeline_endpoint(
    range: str = _RANGE30_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _QualityTimelineOut:
    try:
        report = await compute_quality_timeline(session, org_id=user.org_id, range_key=range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _QualityTimelineOut.model_validate(report)


@router.get(
    "/whatsapp/ai-metrics",
    response_model=_AIMetricsOut,
    summary="AI response rate + escalation rate + AI-only completion proxy",
)
async def whatsapp_ai_metrics_endpoint(
    range: str = _RANGE30_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _AIMetricsOut:
    try:
        report = await compute_ai_metrics(session, org_id=user.org_id, range_key=range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _AIMetricsOut.model_validate(report)


# --- Ad attribution (whatsapp-platform-upgrade Step 24) ---------------------


class _AdAttributionRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: str | None
    campaign_name: str | None
    ad_id: str | None
    ad_name: str | None
    conversations: int
    leads: int
    revenue: float


class _AdAttributionReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    range: str
    rows: list[_AdAttributionRowOut]
    total_conversations: int
    total_leads: int
    total_revenue: float


@router.get(
    "/whatsapp/ad-attribution",
    response_model=_AdAttributionReportOut,
    summary="Per-campaign click-to-WhatsApp conversion + revenue",
)
async def whatsapp_ad_attribution_endpoint(
    range: str = _RANGE30_QUERY,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _AdAttributionReportOut:
    try:
        report = await compute_ad_attribution(session, org_id=user.org_id, range_key=range)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _AdAttributionReportOut.model_validate(report)


# --- A/B comparison (whatsapp-platform-upgrade Step 29) --------------------


class _AbVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    variant: str
    template_id: str | None
    template_name: str | None
    sent: int
    delivered: int
    read: int
    replied: int
    failed: int
    reply_rate: float
    read_rate: float


class _AbComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: uuid.UUID
    is_ab_test: bool
    winner_metric: str | None
    winning_variant: str | None
    winner_decided_at: datetime | None
    a: _AbVariantOut | None
    b: _AbVariantOut | None


@router.get(
    "/campaigns/{campaign_id}/ab-comparison",
    response_model=_AbComparisonOut,
    summary="Per-variant funnel + rates for A/B campaigns",
)
async def campaign_ab_comparison_endpoint(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permissions("whatsapp.analytics.read")),
    session: AsyncSession = Depends(get_db),
) -> _AbComparisonOut:
    report = await compute_ab_comparison(session, org_id=user.org_id, campaign_id=campaign_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="campaign not found",
        )
    return _AbComparisonOut.model_validate(report)
