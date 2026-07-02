"""Pydantic v2 schemas for the call-center module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.calls.models import CallDirection
from src.app.shared.schemas import ORMModel, PaginatedResponse

# --- Outcomes (config) ----------------------------------------------------


class CallOutcomeCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#6b7280", max_length=32)
    display_order: int = Field(default=0, ge=0)


class CallOutcomeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    color: str | None = Field(default=None, max_length=32)
    display_order: int | None = Field(default=None, ge=0)


class CallOutcomeOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    key: str
    label: str
    color: str
    display_order: int
    created_at: datetime


# --- Calls ---------------------------------------------------------------


class CallCreate(BaseModel):
    contact_id: uuid.UUID | None = None
    direction: CallDirection
    started_at: datetime
    duration_sec: int = Field(default=0, ge=0)
    outcome_id: uuid.UUID | None = None
    notes: str | None = None
    recording_url: str | None = Field(default=None, max_length=512)
    assigned_to_id: uuid.UUID | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class CallUpdate(BaseModel):
    contact_id: uuid.UUID | None = None
    duration_sec: int | None = Field(default=None, ge=0)
    outcome_id: uuid.UUID | None = None
    notes: str | None = None
    recording_url: str | None = Field(default=None, max_length=512)
    assigned_to_id: uuid.UUID | None = None
    custom_data: dict[str, Any] | None = None


class CallOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: uuid.UUID | None
    direction: CallDirection
    started_at: datetime
    duration_sec: int
    outcome_id: uuid.UUID | None
    notes: str | None
    recording_url: str | None
    # `recording_file_path` is intentionally NOT exposed to the client —
    # it's an internal filesystem path. The frontend derives whether a
    # recording exists from `has_recording` + streams it via
    # `GET /calls/{id}/recording`.
    has_recording: bool = False
    assigned_to_id: uuid.UUID | None
    custom_data: dict[str, Any]
    created_at: datetime

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):  # type: ignore[override]
        # Derive `has_recording` from the private column so callers
        # can still `CallOut.model_validate(orm_row)` unchanged.
        has_rec = bool(getattr(obj, "recording_file_path", None))
        instance = super().model_validate(obj, *args, **kwargs)
        instance.has_recording = has_rec
        return instance


CallListResponse = PaginatedResponse[CallOut]


# --- Transcript -----------------------------------------------------------


class CallTranscriptUpsert(BaseModel):
    """Idempotent set — replaces the single transcript row for a call."""

    text: str = Field(min_length=1)
    language: str | None = Field(default=None, max_length=16)


class CallTranscriptOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    call_id: uuid.UUID
    text: str
    language: str | None
    created_at: datetime


# --- Analytics ------------------------------------------------------------


class OutcomeDistributionRow(BaseModel):
    outcome_id: uuid.UUID | None
    outcome_key: str | None
    outcome_label: str | None
    outcome_color: str | None
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
