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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.appointments.models import AppointmentStatus
from src.app.shared.schemas import TimestampedOrgScopedOut


class AppointmentCreate(BaseModel):
    contact_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=64)
    scheduled_at: datetime
    duration_min: int = Field(ge=1, le=24 * 60)
    location: str | None = Field(default=None, max_length=255)
    assigned_to_id: uuid.UUID
    custom_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentUpdate(BaseModel):
    """Partial update. `contact_id` is intentionally not editable —
    moving an appointment to a different contact is rare enough that
    delete + recreate is cleaner than another code path."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=64)
    scheduled_at: datetime | None = None
    duration_min: int | None = Field(default=None, ge=1, le=24 * 60)
    location: str | None = Field(default=None, max_length=255)
    status: AppointmentStatus | None = None
    assigned_to_id: uuid.UUID | None = None
    custom_data: dict[str, Any] | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    contact_id: uuid.UUID
    title: str
    purpose: str | None
    scheduled_at: datetime
    duration_min: int
    location: str | None
    status: AppointmentStatus
    assigned_to_id: uuid.UUID
    custom_data: dict[str, Any]
    last_activity_at: datetime | None


# --- Reschedule / reassign / bulk-action shapes ----------------------------


class AppointmentReschedule(BaseModel):
    """Shift the slot of an existing appointment without going through the
    full edit form. `reason` is optional free text that lands on the
    audit `reschedule` activity for the contact's timeline."""

    scheduled_at: datetime
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentReassign(BaseModel):
    """Single-row reassign. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkReassign(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkCancel(BaseModel):
    """Bulk-cancel. Per-row state-machine check applies — only rows
    currently in `scheduled` can move to `cancelled`."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentBulkDelete(BaseModel):
    """Bulk hard-delete. No state-machine check — any status is
    delete-eligible (matches the single-row `DELETE /{id}`). Row cap
    mirrors bulk-reassign / bulk-cancel."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)

    model_config = ConfigDict(str_strip_whitespace=True)


class AppointmentHydrateRequest(BaseModel):
    """Payload for ``POST /appointments/hydrate`` — batch fetch by ids.
    Powers list pages that need to render appointment summaries against
    ids referenced from another table (e.g. the furniture pack's
    field-ops schedule view) without the N-way ``GET /{id}`` fan-out."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class AppointmentBulkReassignResult(BaseModel):
    reassigned: int


class AppointmentBulkDeleteResult(BaseModel):
    """Number of rows actually deleted (ids not in the caller's org are
    dropped silently by the DAL's `list_appointments_by_ids_in_org`
    scope — same partial-success semantic as bulk-cancel)."""

    deleted: int


class AppointmentBulkCancelResult(BaseModel):
    """`cancelled` counts rows actually transitioned this call.
    `skipped` counts rows ignored because they weren't in `scheduled`
    (already completed/cancelled/no_show). Mirrors the partial-success
    pattern used by walk-ins bulk-checkout.

    `skipped_by_status` breaks the skipped total down by the terminal
    state that blocked the cancel — the UI uses it to build an
    actionable message ("2 already completed — delete them instead of
    cancelling") rather than the vague "skipped" toast."""

    cancelled: int
    skipped: int
    skipped_by_status: dict[str, int] = Field(default_factory=dict)
