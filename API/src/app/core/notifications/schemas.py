"""Pydantic v2 schemas for the notifications module.

`type` is free-text so modules can declare their own keys without a
schema migration. The REST shape mirrors the wire-format pushed over
the WebSocket — same object, same field names, so the frontend has
one parser.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.notifications.models import NotificationChannel
from src.app.shared.schemas import ORMModel


class NotificationOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: Optional[str]
    payload: dict[str, Any]
    read_at: Optional[datetime]
    created_at: datetime


class NotificationPreferenceOut(ORMModel):

    type: str
    channel: NotificationChannel
    enabled: bool


class PreferenceUpdate(BaseModel):
    """Per-channel toggles for a single `type`. Omitted channels are
    left untouched. Provided channels are upserted to the boolean
    value supplied."""

    in_app: Optional[bool] = None
    email: Optional[bool] = None
    push: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")


class ReadAllResponse(BaseModel):
    marked: int = Field(ge=0)
