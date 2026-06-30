"""Pydantic v2 schemas for the furniture-pack field-ops module."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from src.app.core.appointments.schemas import AppointmentCreate
from src.app.packs.furniture.modules.field_ops.models import FieldVisitPurpose
from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut

# --- Field visits ---------------------------------------------------------


class FieldVisitCreate(BaseModel):
    """Atomic create: caller passes an `AppointmentCreate` body and the
    pack-specific visit fields. The service creates both the
    appointment and the visit in one transaction.
    """

    appointment: AppointmentCreate
    purpose: FieldVisitPurpose
    custom_order_id: uuid.UUID | None = None
    notes: str | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class FieldVisitUpdate(BaseModel):
    purpose: FieldVisitPurpose | None = None
    custom_order_id: uuid.UUID | None = None
    notes: str | None = None
    signature_url: str | None = Field(default=None, max_length=512)
    custom_data: dict[str, Any] | None = None


class FieldVisitOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    appointment_id: uuid.UUID
    purpose: FieldVisitPurpose
    custom_order_id: uuid.UUID | None
    notes: str | None
    completed_at: datetime | None
    signature_url: str | None
    custom_data: dict[str, Any]


class FieldVisitListResponse(BaseModel):
    items: list[FieldVisitOut]
    total: int
    page: int
    size: int


# --- Complete action -----------------------------------------------------


class MeasurementCopyback(BaseModel):
    """One captured measurement to copy back to the linked custom order
    when the visit is marked complete. Mirrors `MeasurementCreate` on
    the custom-orders module but lives here so the field-ops API is
    self-contained for the staff portal.
    """

    item_label: str = Field(min_length=1, max_length=128)
    length_cm: Decimal | None = Field(default=None, ge=0)
    width_cm: Decimal | None = Field(default=None, ge=0)
    height_cm: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class FieldVisitCompletePayload(BaseModel):
    notes: str | None = None
    signature_url: str | None = Field(default=None, max_length=512)
    measurements: list[MeasurementCopyback] = Field(default_factory=list)


# --- Photos --------------------------------------------------------------


class FieldVisitPhotoOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    visit_id: uuid.UUID
    url: str
    caption: str | None
    taken_at: datetime | None
    created_at: datetime
