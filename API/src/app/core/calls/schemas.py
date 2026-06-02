"""Pydantic v2 schemas for the call-center module."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.calls.models import CallDirection
from src.app.shared.schemas import PaginatedResponse


# --- Outcomes (config) ----------------------------------------------------


class CallOutcomeCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#6b7280", max_length=32)
    display_order: int = Field(default=0, ge=0)


class CallOutcomeUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=128)
    color: Optional[str] = Field(default=None, max_length=32)
    display_order: Optional[int] = Field(default=None, ge=0)


class CallOutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    key: str
    label: str
    color: str
    display_order: int
    created_at: datetime


# --- Calls ---------------------------------------------------------------


class CallCreate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    direction: CallDirection
    started_at: datetime
    duration_sec: int = Field(default=0, ge=0)
    outcome_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    recording_url: Optional[str] = Field(default=None, max_length=512)
    assigned_to_id: Optional[uuid.UUID] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class CallUpdate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    duration_sec: Optional[int] = Field(default=None, ge=0)
    outcome_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    recording_url: Optional[str] = Field(default=None, max_length=512)
    assigned_to_id: Optional[uuid.UUID] = None
    custom_data: Optional[dict[str, Any]] = None


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: Optional[uuid.UUID]
    direction: CallDirection
    started_at: datetime
    duration_sec: int
    outcome_id: Optional[uuid.UUID]
    notes: Optional[str]
    recording_url: Optional[str]
    assigned_to_id: Optional[uuid.UUID]
    custom_data: dict[str, Any]
    created_at: datetime


CallListResponse = PaginatedResponse[CallOut]


# --- Transcript -----------------------------------------------------------


class CallTranscriptUpsert(BaseModel):
    """Idempotent set — replaces the single transcript row for a call."""

    text: str = Field(min_length=1)
    language: Optional[str] = Field(default=None, max_length=16)


class CallTranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    call_id: uuid.UUID
    text: str
    language: Optional[str]
    created_at: datetime


# --- Analytics ------------------------------------------------------------


class OutcomeDistributionRow(BaseModel):
    outcome_id: Optional[uuid.UUID]
    outcome_key: Optional[str]
    outcome_label: Optional[str]
    outcome_color: Optional[str]
    count: int


class DailyVolumeRow(BaseModel):
    day: date
    count: int


class DirectionSplitRow(BaseModel):
    direction: CallDirection
    count: int


class CallAnalyticsOut(BaseModel):
    """Three chart-ready arrays over the requested `from..to` window."""

    from_: date = Field(alias="from")
    to: date
    outcomes: list[OutcomeDistributionRow]
    daily: list[DailyVolumeRow]
    direction: list[DirectionSplitRow]

    model_config = ConfigDict(populate_by_name=True)
