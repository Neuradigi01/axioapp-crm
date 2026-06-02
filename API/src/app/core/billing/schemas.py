"""Pydantic v2 schemas for the core billing engine."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.app.core.billing.models import InvoiceStatus, PaymentMethod
from src.app.shared.schemas import ORMModel, PaginatedResponse, TimestampedOrgScopedOut


# --- Invoices -------------------------------------------------------------


class InvoiceCreate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)


class InvoiceUpdate(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    discount_amount: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None
    custom_data: Optional[dict[str, Any]] = None


class InvoiceLineCreate(BaseModel):
    catalog_item_id: Optional[uuid.UUID] = None
    description: str = Field(min_length=1, max_length=255)
    qty: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0)
    tax_pct: Optional[Decimal] = Field(default=None, ge=0, le=100)


class InvoiceLineOut(ORMModel):

    id: uuid.UUID
    invoice_id: uuid.UUID
    catalog_item_id: Optional[uuid.UUID]
    description: str
    qty: int
    unit_price: Decimal
    line_subtotal: Decimal
    tax_pct: Decimal
    line_total: Decimal
    created_at: datetime


class InvoiceOut(TimestampedOrgScopedOut):

    id: uuid.UUID
    number: Optional[int]
    contact_id: Optional[uuid.UUID]
    status: InvoiceStatus
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total: Decimal
    currency: str
    gst_number: Optional[str]
    tax_rate_snapshot: Optional[Decimal]
    issued_at: Optional[datetime]
    paid_at: Optional[datetime]
    payment_method: Optional[PaymentMethod]
    notes: Optional[str]
    custom_data: dict[str, Any]


class InvoiceWithLines(InvoiceOut):
    lines: list[InvoiceLineOut] = Field(default_factory=list)


InvoiceListResponse = PaginatedResponse[InvoiceOut]


# --- Issuance + payments -------------------------------------------------


class IssuePayload(BaseModel):
    """Issuing snapshots `tax_rate` + `gst_number` from org settings."""

    notes: Optional[str] = None


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = None


class PaymentOut(ORMModel):

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    method: PaymentMethod
    reference: Optional[str]
    received_at: datetime
    notes: Optional[str]
    created_at: datetime
