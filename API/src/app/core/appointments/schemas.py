"""Pydantic v2 schemas for the appointments module.

`status` is server-managed on create (defaults to `scheduled`) but
editable on update so the assignee can mark `completed` / `cancelled`
/ `no_show`. `assigned_to_id` is required on create — every
appointment is owned by someone for conflict-detection to be
meaningful.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.appointments.models import AppointmentStatus


class AppointmentCreate(BaseModel):
    contact_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    purpose: Optional[str] = Field(default=None, max_length=64)
    scheduled_at: datetime
    duration_min: int = Field(ge=1, le=24 * 60)
    location: Optional[str] = Field(default=None, max_length=255)
    assigned_to_id: uuid.UUID
    custom_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentUpdate(BaseModel):
    """Partial update. `contact_id` is intentionally not editable —
    moving an appointment to a different contact is rare enough that
    delete + recreate is cleaner than another code path."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    purpose: Optional[str] = Field(default=None, max_length=64)
    scheduled_at: Optional[datetime] = None
    duration_min: Optional[int] = Field(default=None, ge=1, le=24 * 60)
    location: Optional[str] = Field(default=None, max_length=255)
    status: Optional[AppointmentStatus] = None
    assigned_to_id: Optional[uuid.UUID] = None
    custom_data: Optional[dict[str, Any]] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: uuid.UUID
    title: str
    purpose: Optional[str]
    scheduled_at: datetime
    duration_min: int
    location: Optional[str]
    status: AppointmentStatus
    assigned_to_id: uuid.UUID
    custom_data: dict[str, Any]
    last_activity_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# --- Reschedule / reassign / bulk-action shapes ----------------------------


class AppointmentReschedule(BaseModel):
    """Shift the slot of an existing appointment without going through the
    full edit form. `reason` is optional free text that lands on the
    audit `reschedule` activity for the contact's timeline."""

    scheduled_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentReassign(BaseModel):
    """Single-row reassign. `null` clears the owner."""

    assigned_to_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkReassign(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: Optional[uuid.UUID] = None
    note: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkCancel(BaseModel):
    """Bulk-cancel. Per-row state-machine check applies — only rows
    currently in `scheduled` can move to `cancelled`."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkReassignResult(BaseModel):
    reassigned: int


class AppointmentBulkCancelResult(BaseModel):
    """`cancelled` counts rows actually transitioned this call.
    `skipped` counts rows ignored because they weren't in `scheduled`
    (already completed/cancelled/no_show). Mirrors the partial-success
    pattern used by walk-ins bulk-checkout."""

    cancelled: int
    skipped: int
