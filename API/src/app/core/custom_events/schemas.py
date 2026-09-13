"""Pydantic schemas for the custom events API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_EVENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CustomEventCreate(BaseModel):
    """Payload for ``POST /api/v1/custom-events``.

    ``event_key`` — lowercase snake_case, 1..64 chars starting with a
    letter. This is the stable identifier that publishes on the bus
    (``custom.<event_key>``); once created it cannot be changed
    (rename would silently break every workflow that subscribed to
    the old name). Owners can edit ``name`` + ``description`` freely.
    """

    event_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("event_key")
    @classmethod
    def _key_shape(cls, v: str) -> str:
        if not _EVENT_KEY_RE.match(v):
            raise ValueError(
                "event_key must be lowercase snake_case, start with a letter, "
                "and contain only [a-z0-9_] (max 64 chars)."
            )
        return v


class CustomEventUpdate(BaseModel):
    """Patch-style update. Only ``name`` + ``description`` are editable."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


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
