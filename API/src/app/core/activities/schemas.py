"""Pydantic v2 schemas for the activities module.

The HTTP `POST /activities` endpoint is **only for manual notes** — the
internal `activities.log(...)` helper is what other modules use for
system events (call ended, status changed, …). `ActivityCreate`
enforces `type='note'` and `payload={"text": <non-empty string>}` so
operators can't sneak in a fake call/email row from a browser.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.app.core.activities.models import ActivityType
from src.app.shared.schemas import ORMModel, PaginatedResponse

_ENTITY_TYPE_MIN = 1
_ENTITY_TYPE_MAX = 64
_NOTE_TEXT_MAX = 4000


class ActivityCreate(BaseModel):
    """HTTP-creatable subset: notes only, with a text payload."""

    entity_type: str = Field(min_length=_ENTITY_TYPE_MIN, max_length=_ENTITY_TYPE_MAX)
    entity_id: uuid.UUID
    type: ActivityType
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _only_notes_over_http(cls, value: ActivityType) -> ActivityType:
        if value is not ActivityType.note:
            raise ValueError(
                "HTTP-created activities must be type='note'; "
                "other types are emitted by the server."
            )
        return value

    @field_validator("payload")
    @classmethod
    def _payload_has_text(cls, value: dict[str, Any]) -> dict[str, Any]:
        text = value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("payload.text must be a non-empty string")
        if len(text) > _NOTE_TEXT_MAX:
            raise ValueError(f"payload.text exceeds {_NOTE_TEXT_MAX} characters")
        return {"text": text.strip()}


class ActivityOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    type: ActivityType
    payload: dict[str, Any]
    user_id: uuid.UUID | None
    created_at: datetime


ActivityListResponse = PaginatedResponse[ActivityOut]
