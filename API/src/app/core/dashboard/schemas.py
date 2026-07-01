"""Pydantic v2 response shapes for the dashboard endpoint."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from src.app.core.tasks.models import (
    TaskFollowupType,
    TaskPriority,
    TaskStatus,
)
from src.app.shared.schemas import ORMModel

Format = Literal["number", "currency", "percent", "text", "leaderboard"]
Scope = Literal["org", "personal"]
TrendMetric = Literal["leads_created", "pipeline_value", "calls", "appointments"]
TrendRange = Literal["7d", "30d", "90d", "365d"]

FollowupBucket = Literal["today", "pending", "completed_today", "overdue", "missed"]
UpcomingScope = Literal["today", "next5"]


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


class FollowupCounts(BaseModel):
    """The five KPI counts that drive the dashboard's follow-up cards
    and the widget's chip counters. All counts are computed against
    the caller's scope (org / personal)."""

    today_total: int
    pending_today: int
    completed_today: int
    overdue: int
    missed_last_7d: int


class FollowupAssignedTo(BaseModel):
    """Denormalised assignee identity carried on each row so the widget
    doesn't need a second round-trip for user lookups."""

    id: uuid.UUID
    name: str


class FollowupLinkedEntity(BaseModel):
    """Non-null when the task points at a contact / lead / walk-in.
    NULL for standalone tasks ("review pipeline"). The widget renders
    a fallback chip when this is absent."""

    type: str
    id: uuid.UUID
    label: str


class FollowupItem(BaseModel):
    """One row in the follow-ups widget list."""

    id: uuid.UUID
    title: str
    due_at: datetime | None
    priority: TaskPriority
    status: TaskStatus
    followup_type: TaskFollowupType | None
    notes_preview: str | None
    assigned_to: FollowupAssignedTo
    linked_entity: FollowupLinkedEntity | None


class FollowupsResponse(BaseModel):
    """Everything the follow-ups widget needs in one round-trip: scope
    resolution, KPI counts, and the paginated list of matching rows."""

    scope: Scope
    bucket: FollowupBucket
    counts: FollowupCounts
    page: int
    page_size: int
    total: int
    items: list[FollowupItem]


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
