"""Pydantic v2 schemas for the furniture-pack inventory module."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from src.app.packs.furniture.modules.inventory.models import (
    AlertPriority,
    AlertSeverity,
    AlertStatus,
    MovementType,
)
from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut

# --- Warehouses ----------------------------------------------------------


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    address: str | None = None
    contact_phone: str | None = Field(default=None, max_length=32)
    is_default: bool = False


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    address: str | None = None
    contact_phone: str | None = Field(default=None, max_length=32)
    is_default: bool | None = None


class WarehouseOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    name: str
    address: str | None
    contact_phone: str | None
    is_default: bool


# --- Items ----------------------------------------------------------------


class InventoryItemCreate(BaseModel):
    catalog_item_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    material: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=64)
    finish: str | None = Field(default=None, max_length=64)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    reorder_level: int = Field(default=0, ge=0)
    custom_data: dict[str, Any] = Field(default_factory=dict)
    is_best_seller: bool = False
    is_active: bool = True


class InventoryItemUpdate(BaseModel):
    catalog_item_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    material: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=64)
    finish: str | None = Field(default=None, max_length=64)
    dimensions: dict[str, Any] | None = None
    reorder_level: int | None = Field(default=None, ge=0)
    custom_data: dict[str, Any] | None = None
    is_best_seller: bool | None = None
    is_active: bool | None = None


class InventoryItemHydrateRequest(BaseModel):
    """Payload for ``POST /inventory/items/hydrate`` — batch fetch by
    ids. Powers the stock-alerts page (and any future consumer) that
    needs to render item context per row without the N-way
    ``GET /inventory/items/{id}`` fan-out."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class InventoryItemOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    catalog_item_id: uuid.UUID | None
    warehouse_id: uuid.UUID
    sku: str
    material: str | None
    color: str | None
    finish: str | None
    dimensions: dict[str, Any]
    qty_on_hand: int
    qty_reserved: int
    reorder_level: int
    last_received_at: datetime | None
    custom_data: dict[str, Any]
    cover_url: str | None
    is_best_seller: bool
    is_active: bool


class InventoryItemFullCreate(BaseModel):
    """Atomic create: catalog row + inventory row in one transaction.

    The catalog row is what walk-in/lead pickers reference; the
    inventory row carries the physical stock numbers. The endpoint
    enforces both inserts succeed-or-fail together so we never end up
    with a half-created product.
    """

    # Catalog-side
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    description: str | None = None

    # Inventory-side
    warehouse_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    material: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=64)
    finish: str | None = Field(default=None, max_length=64)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    reorder_level: int = Field(default=0, ge=0)
    is_best_seller: bool = False
    is_active: bool = True


class CoverUploadResponse(BaseModel):
    cover_url: str


class InventoryItemListResponse(BaseModel):
    items: list[InventoryItemOut]
    total: int
    page: int
    size: int


# --- Movements -----------------------------------------------------------


class MovementCreate(BaseModel):
    type: MovementType
    qty: int = Field(
        description=("Positive for receipt/dispatch/transfer; signed for adjust."),
    )
    reference_type: str | None = Field(default=None, max_length=64)
    reference_id: uuid.UUID | None = None
    notes: str | None = None


class MovementOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    item_id: uuid.UUID
    type: MovementType
    qty: int
    reference_type: str | None
    reference_id: uuid.UUID | None
    notes: str | None
    user_id: uuid.UUID | None
    created_at: datetime


# --- Alerts --------------------------------------------------------------


class StockAlertOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    item_id: uuid.UUID
    severity: AlertSeverity
    priority: AlertPriority
    suggested_reorder_qty: int
    status: AlertStatus
    created_at: datetime
    closed_at: datetime | None


class StockAlertPatch(BaseModel):
    status: AlertStatus
