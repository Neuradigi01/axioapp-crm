"""Pydantic v2 response shapes for the dashboard endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


Format = Literal["number", "currency", "percent", "text", "leaderboard"]
Scope = Literal["org", "personal"]


class DashboardCard(BaseModel):
    """A single KPI on the dashboard.

    The frontend renders generically based on `format` — adding a new
    card here means one extra entry in the service + one template
    branch keyed on `format`. No per-card components.

    `value` is `Any` because the leaderboard format carries a
    `list[{name, count}]` instead of a scalar.
    """
    key: str
    label: str
    value: Any
    format: Format
    link: str | None = None


class ActivityItem(BaseModel):
    """One row in the dashboard's recent-activity feed."""
    action: str
    entity_label: str
    actor_name: str
    at: datetime


class UpcomingAppointment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
