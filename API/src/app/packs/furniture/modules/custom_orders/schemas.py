"""Pydantic v2 schemas for the furniture-pack custom-orders module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut

# --- Custom Orders --------------------------------------------------------


class CustomOrderCreate(BaseModel):
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    requirement: str | None = None
    materials: dict[str, Any] = Field(default_factory=dict)
    color: str | None = Field(default=None, max_length=64)
    finish: str | None = Field(default=None, max_length=64)
    assigned_to_id: uuid.UUID | None = None
    expected_delivery_date: date | None = None
    total_amount: Decimal = Field(default=Decimal("0"), ge=0)
    advance_paid: Decimal = Field(default=Decimal("0"), ge=0)
    custom_data: dict[str, Any] = Field(default_factory=dict)


class CustomOrderUpdate(BaseModel):
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    requirement: str | None = None
    materials: dict[str, Any] | None = None
    color: str | None = Field(default=None, max_length=64)
    finish: str | None = Field(default=None, max_length=64)
    assigned_to_id: uuid.UUID | None = None
    expected_delivery_date: date | None = None
    total_amount: Decimal | None = Field(default=None, ge=0)
    advance_paid: Decimal | None = Field(default=None, ge=0)
    custom_data: dict[str, Any] | None = None


class CustomOrderOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    title: str
    requirement: str | None
    materials: dict[str, Any]
    color: str | None
    finish: str | None
    pipeline_stage: str
    assigned_to_id: uuid.UUID | None
    expected_delivery_date: date | None
    total_amount: Decimal
    advance_paid: Decimal
    custom_data: dict[str, Any]


class CustomOrderListResponse(BaseModel):
    items: list[CustomOrderOut]
    total: int
    page: int
    size: int


class MoveStagePayload(BaseModel):
    to_stage: str = Field(min_length=1, max_length=64)
    notes: str | None = None


# --- Measurements --------------------------------------------------------


class MeasurementCreate(BaseModel):
    item_label: str = Field(min_length=1, max_length=128)
    length_cm: Decimal | None = Field(default=None, ge=0)
    width_cm: Decimal | None = Field(default=None, ge=0)
    height_cm: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class MeasurementOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    order_id: uuid.UUID
    item_label: str
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    notes: str | None
    created_at: datetime


# --- Photos --------------------------------------------------------------


class PhotoOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    order_id: uuid.UUID
    url: str
    caption: str | None
    taken_at: datetime | None
    created_at: datetime


# --- Stage history -------------------------------------------------------


class StageHistoryOut(ORMModel):
    id: uuid.UUID
    order_id: uuid.UUID
    from_stage: str | None
    to_stage: str
    user_id: uuid.UUID | None
    notes: str | None
    changed_at: datetime
