"""Pydantic v2 schemas for the furniture-pack field-ops module."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.appointments.schemas import AppointmentCreate
from src.app.packs.furniture.modules.field_ops.models import FieldVisitPurpose


# --- Field visits ---------------------------------------------------------


class FieldVisitCreate(BaseModel):
    """Atomic create: caller passes an `AppointmentCreate` body and the
    pack-specific visit fields. The service creates both the
    appointment and the visit in one transaction.
    """

    appointment: AppointmentCreate
    purpose: FieldVisitPurpose
    custom_order_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class FieldVisitUpdate(BaseModel):
    purpose: Optional[FieldVisitPurpose] = None
    custom_order_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    signature_url: Optional[str] = Field(default=None, max_length=512)
    custom_data: Optional[dict[str, Any]] = None


class FieldVisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    appointment_id: uuid.UUID
    purpose: FieldVisitPurpose
    custom_order_id: Optional[uuid.UUID]
    notes: Optional[str]
    completed_at: Optional[datetime]
    signature_url: Optional[str]
    custom_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


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
    length_cm: Optional[Decimal] = Field(default=None, ge=0)
    width_cm: Optional[Decimal] = Field(default=None, ge=0)
    height_cm: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class FieldVisitCompletePayload(BaseModel):
    notes: Optional[str] = None
    signature_url: Optional[str] = Field(default=None, max_length=512)
    measurements: list[MeasurementCopyback] = Field(default_factory=list)


# --- Photos --------------------------------------------------------------


class FieldVisitPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    visit_id: uuid.UUID
    url: str
    caption: Optional[str]
    taken_at: Optional[datetime]
    created_at: datetime
