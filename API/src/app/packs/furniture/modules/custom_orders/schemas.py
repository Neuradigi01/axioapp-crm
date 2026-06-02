"""Pydantic v2 schemas for the furniture-pack custom-orders module."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.app.shared.schemas import ORMModel


# --- Custom Orders --------------------------------------------------------


class CustomOrderCreate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    lead_id: Optional[uuid.UUID] = None
    title: str = Field(min_length=1, max_length=255)
    requirement: Optional[str] = None
    materials: dict[str, Any] = Field(default_factory=dict)
    color: Optional[str] = Field(default=None, max_length=64)
    finish: Optional[str] = Field(default=None, max_length=64)
    assigned_to_id: Optional[uuid.UUID] = None
    expected_delivery_date: Optional[date] = None
    total_amount: Decimal = Field(default=Decimal("0"), ge=0)
    advance_paid: Decimal = Field(default=Decimal("0"), ge=0)
    custom_data: dict[str, Any] = Field(default_factory=dict)


class CustomOrderUpdate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    lead_id: Optional[uuid.UUID] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    requirement: Optional[str] = None
    materials: Optional[dict[str, Any]] = None
    color: Optional[str] = Field(default=None, max_length=64)
    finish: Optional[str] = Field(default=None, max_length=64)
    assigned_to_id: Optional[uuid.UUID] = None
    expected_delivery_date: Optional[date] = None
    total_amount: Optional[Decimal] = Field(default=None, ge=0)
    advance_paid: Optional[Decimal] = Field(default=None, ge=0)
    custom_data: Optional[dict[str, Any]] = None


class CustomOrderOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: Optional[uuid.UUID]
    lead_id: Optional[uuid.UUID]
    title: str
    requirement: Optional[str]
    materials: dict[str, Any]
    color: Optional[str]
    finish: Optional[str]
    pipeline_stage: str
    assigned_to_id: Optional[uuid.UUID]
    expected_delivery_date: Optional[date]
    total_amount: Decimal
    advance_paid: Decimal
    custom_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CustomOrderListResponse(BaseModel):
    items: list[CustomOrderOut]
    total: int
    page: int
    size: int


class MoveStagePayload(BaseModel):
    to_stage: str = Field(min_length=1, max_length=64)
    notes: Optional[str] = None


# --- Measurements --------------------------------------------------------


class MeasurementCreate(BaseModel):
    item_label: str = Field(min_length=1, max_length=128)
    length_cm: Optional[Decimal] = Field(default=None, ge=0)
    width_cm: Optional[Decimal] = Field(default=None, ge=0)
    height_cm: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class MeasurementOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    order_id: uuid.UUID
    item_label: str
    length_cm: Optional[Decimal]
    width_cm: Optional[Decimal]
    height_cm: Optional[Decimal]
    notes: Optional[str]
    created_at: datetime


# --- Photos --------------------------------------------------------------


class PhotoOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    order_id: uuid.UUID
    url: str
    caption: Optional[str]
    taken_at: Optional[datetime]
    created_at: datetime


# --- Stage history -------------------------------------------------------


class StageHistoryOut(ORMModel):

    id: uuid.UUID
    order_id: uuid.UUID
    from_stage: Optional[str]
    to_stage: str
    user_id: Optional[uuid.UUID]
    notes: Optional[str]
    changed_at: datetime
