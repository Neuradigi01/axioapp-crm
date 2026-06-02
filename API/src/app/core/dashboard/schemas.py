"""Pydantic v2 response shapes for the dashboard endpoint."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from src.app.shared.schemas import ORMModel


Format = Literal["number", "currency", "percent", "text", "leaderboard"]
Scope = Literal["org", "personal"]
TrendMetric = Literal["leads_created", "pipeline_value", "calls", "appointments"]
TrendRange = Literal["7d", "30d", "90d", "365d"]


DeltaDirection = Literal["up", "down", "flat"]


class DashboardCard(BaseModel):
    """A single KPI on the dashboard.

    The frontend renders generically based on `format` — adding a new
    card here means one extra entry in the service + one template
    branch keyed on `format`. No per-card components.

    `value` is `Any` because the leaderboard format carries a
    `list[{name, count}]` instead of a scalar.

    For scalar formats (`number`, `currency`, `percent`) the three
    `previous_value` / `delta_pct` / `delta_direction` fields are
    always populated so the frontend can render a trend pill. For
    `leaderboard` and `text` formats they stay `None` (no meaningful
    period comparison).
    """
    key: str
    label: str
    value: Any
    format: Format
    link: str | None = None
    previous_value: float | int | None = None
    delta_pct: float | None = None
    delta_direction: DeltaDirection | None = None


class ActivityItem(BaseModel):
    """One row in the dashboard's recent-activity feed."""
    action: str
    entity_label: str
    actor_name: str
    at: datetime


class UpcomingAppointment(ORMModel):
    id: uuid.UUID
    title: str
    starts_at: datetime
    with_contact_name: str


class Greeting(BaseModel):
    first_name: str
    role_name: str
    org_name: str


class DashboardSummary(BaseModel):
    greeting: Greeting
    scope: Scope
    cards: list[DashboardCard]
    recent_activity: list[ActivityItem]
    upcoming_appointments: list[UpcomingAppointment]


class DashboardTrendPoint(BaseModel):
    """One day-bucket in a trend series. UTC date, never null value."""
    date: date
    value: float


class DashboardTrendResponse(BaseModel):
    """Time-series payload for the dashboard trend chart.

    `points` always has exactly `range_days` entries sorted ascending —
    missing buckets are zero-filled in the service so the frontend can
    render without gap-handling logic.
    """
    metric: TrendMetric
    range: TrendRange
    scope: Scope
    points: list[DashboardTrendPoint]


class FunnelStageBucket(BaseModel):
    """One stage of the leads pipeline with its in-range lead count."""
    stage_id: uuid.UUID
    stage_name: str
    stage_order: int
    count: int


class DashboardFunnelResponse(BaseModel):
    """Funnel payload — every active non-terminal pipeline stage + won/lost.

    `stages` always contains every non-terminal stage (sorted by
    `stage_order` ascending) so the chart bar count is deterministic
    and empty stages render as zero-height bars rather than gaps.
    `won_count` / `lost_count` are reported separately because they
    correspond to the terminal `Lead.status` values rather than to
    stages in the funnel chart itself; `total_leads_in_range` =
    sum(stages) + won_count + lost_count.
    """
    range: TrendRange
    scope: Scope
    total_leads_in_range: int
    stages: list[FunnelStageBucket]
    won_count: int
    lost_count: int
