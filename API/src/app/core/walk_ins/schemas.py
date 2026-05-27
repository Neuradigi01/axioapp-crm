"""Pydantic v2 schemas for the walk-ins module.

`QuickRegisterPayload` is the reception-desk one-shot: phone is the
required key the service uses to look up an existing contact (and
create one if missing). `QuickRegisterResponse` returns both the
walk-in row and the resolved contact so the caller can show the
contact's existing tags / history alongside the new walk-in.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.app.core.contacts.schemas import ContactOut
from src.app.core.walk_ins.models import WalkInStatus


class WalkInCreate(BaseModel):
    contact_id: uuid.UUID
    requirement: Optional[str] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    assigned_to_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class WalkInUpdate(BaseModel):
    """Partial update. `time_in` / `time_out` are server-managed (via
    `quick_register` and `checkout` respectively), so they're not in
    this schema — the timing fields don't get rewritten through a
    generic PATCH."""

    requirement: Optional[str] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    assigned_to_id: Optional[uuid.UUID] = None
    status: Optional[WalkInStatus] = None
    notes: Optional[str] = None
    custom_data: Optional[dict[str, Any]] = None


class QuickRegisterPayload(BaseModel):
    """Reception-desk one-shot. `phone` is required so the service has
    a deduplication key; everything else is optional."""

    phone: str = Field(min_length=1, max_length=32)
    full_name: str = Field(min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    source: Optional[str] = Field(default=None, max_length=64)
    requirement: Optional[str] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    assigned_to_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class WalkInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: uuid.UUID
    time_in: datetime
    time_out: Optional[datetime]
    duration_min: Optional[Decimal]
    requirement: Optional[str]
    budget: Optional[Decimal]
    assigned_to_id: Optional[uuid.UUID]
    status: WalkInStatus
    notes: Optional[str]
    custom_data: dict[str, Any]
    last_activity_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class QuickRegisterResponse(BaseModel):
    """Return both the walk-in and its resolved contact so the
    reception-desk UI can show prior tags / source on first paint."""

    walk_in: WalkInOut
    contact: ContactOut
    contact_was_created: bool
