"""Pydantic schemas for the custom events API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EVENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


ScheduleType = Literal["manual", "date_field"]
ScheduleSource = Literal["system", "custom"]
RecurringMode = Literal["none", "yearly", "monthly"]
EntityType = Literal["contact", "lead", "appointment"]


class ScheduleConfig(BaseModel):
    """Fire-schedule sub-payload for a date-triggered event.

    Only present when the parent's ``schedule_type='date_field'``.
    Every field is required in that case; the pydantic model_validator
    on the parent (Create/Update) enforces the coupling.
    """

    source: ScheduleSource
    field_ref: str = Field(min_length=1, max_length=128)
    offset_days: int = Field(ge=-365, le=365)
    recurring: RecurringMode
    hour_local: int = Field(ge=0, le=23)
    # 5-minute steps to match the sweep cadence (every 5 min).
    minute_local: int = Field(default=0, ge=0, le=55)

    @field_validator("minute_local")
    @classmethod
    def _minute_step(cls, v: int) -> int:
        if v % 5 != 0:
            raise ValueError("minute_local must be a multiple of 5 (00, 05, … 55).")
        return v

    @field_validator("field_ref")
    @classmethod
    def _ref_shape(cls, v: str) -> str:
        if not _FIELD_REF_RE.match(v):
            raise ValueError("field_ref must be lowercase snake_case (e.g. visa_expiry_date).")
        return v


class CustomEventCreate(BaseModel):
    """Payload for ``POST /api/v1/custom-events``.

    ``event_key`` — lowercase snake_case, 1..64 chars starting with a
    letter. This is the stable identifier that publishes on the bus
    (``custom.<event_key>``); once created it cannot be changed
    (rename would silently break every workflow that subscribed to
    the old name). Owners can edit ``name`` + ``description`` freely.

    ``schedule_type`` defaults to ``'manual'`` (staff clicks Log Event
    to fire). Set to ``'date_field'`` + supply ``schedule`` to have
    the daily sweeper auto-fire on matching contacts.
    """

    event_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    entity_type: EntityType = "contact"
    schedule_type: ScheduleType = "manual"
    schedule: ScheduleConfig | None = None

    @field_validator("event_key")
    @classmethod
    def _key_shape(cls, v: str) -> str:
        if not _EVENT_KEY_RE.match(v):
            raise ValueError(
                "event_key must be lowercase snake_case, start with a letter, "
                "and contain only [a-z0-9_] (max 64 chars)."
            )
        return v

    @model_validator(mode="after")
    def _schedule_matches_type(self) -> CustomEventCreate:
        if self.schedule_type == "date_field" and self.schedule is None:
            raise ValueError("schedule payload required when schedule_type='date_field'.")
        if self.schedule_type == "manual" and self.schedule is not None:
            raise ValueError("schedule payload must be omitted when schedule_type='manual'.")
        return self


class CustomEventUpdate(BaseModel):
    """Patch-style update. ``name`` + ``description`` are editable; the
    fire schedule can be changed too (switching manual↔date_field or
    tweaking any schedule sub-field). Omit ``schedule_type`` to leave
    the current setting untouched.

    ``entity_type`` is INTENTIONALLY not editable — flipping an
    event's entity mid-flight would invalidate the field binding, the
    workflow envelope shape, and every occurrence's ``entity_id``.
    Create a fresh event with a different key if you need a different
    entity.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    schedule_type: ScheduleType | None = None
    schedule: ScheduleConfig | None = None

    @model_validator(mode="after")
    def _schedule_matches_type(self) -> CustomEventUpdate:
        # Only enforce coupling when the caller supplied schedule_type
        # — a bare name/description patch is allowed to skip both.
        if self.schedule_type == "date_field" and self.schedule is None:
            raise ValueError("schedule payload required when switching to 'date_field'.")
        if self.schedule_type == "manual" and self.schedule is not None:
            raise ValueError("schedule payload must be omitted when switching to 'manual'.")
        return self


class CustomEventRead(BaseModel):
    """Row projection returned by list + get + create + update."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_key: str
    name: str
    description: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    entity_type: EntityType = "contact"
    schedule_type: ScheduleType = "manual"
    schedule: ScheduleConfig | None = None


class CustomEventListItem(CustomEventRead):
    """List-page row projection. Adds two aggregate counters the settings
    table renders inline (avoids a per-row lookup from the frontend)."""

    fires_last_30d: int = 0
    workflows_using_count: int = 0


class CustomEventFireRequest(BaseModel):
    """Payload for ``POST /api/v1/custom-events/{id}/fire``.

    ``contact_id`` is optional — some events fire without a specific
    contact (system-wide broadcast). ``payload`` is a free-form dict
    that gets embedded into the bus envelope so workflow conditions
    and template variables can read it.
    """

    contact_id: uuid.UUID | None = None
    payload: dict[str, Any] | None = None


class CustomEventOccurrenceRead(BaseModel):
    """Occurrence log row projection for the detail-page history tab."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    contact_id: uuid.UUID | None
    fired_by_user_id: uuid.UUID | None
    payload: dict[str, Any]
    fired_at: datetime


class CustomEventFireResponse(BaseModel):
    """What ``POST /custom-events/{id}/fire`` returns."""

    occurrence_id: uuid.UUID
    event_type: str  # e.g. "custom.visa_expired"
    fired_at: datetime


__all__ = [
    "CustomEventCreate",
    "CustomEventFireRequest",
    "CustomEventFireResponse",
    "CustomEventListItem",
    "CustomEventOccurrenceRead",
    "CustomEventRead",
    "CustomEventUpdate",
]
