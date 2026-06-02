"""Pydantic v2 schemas for the furniture-pack inventory module."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut
from src.app.packs.furniture.modules.inventory.models import (
    AlertPriority,
    AlertSeverity,
    AlertStatus,
    MovementType,
)


# --- Warehouses ----------------------------------------------------------


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    address: Optional[str] = None
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    is_default: bool = False


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    address: Optional[str] = None
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    is_default: Optional[bool] = None


class WarehouseOut(TimestampedOrgScopedOut):

    id: uuid.UUID
    name: str
    address: Optional[str]
    contact_phone: Optional[str]
    is_default: bool


# --- Items ----------------------------------------------------------------


class InventoryItemCreate(BaseModel):
    catalog_item_id: Optional[uuid.UUID] = None
    warehouse_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    material: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=64)
    finish: Optional[str] = Field(default=None, max_length=64)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    reorder_level: int = Field(default=0, ge=0)
    custom_data: dict[str, Any] = Field(default_factory=dict)
    is_best_seller: bool = False
    is_active: bool = True


class InventoryItemUpdate(BaseModel):
    catalog_item_id: Optional[uuid.UUID] = None
    warehouse_id: Optional[uuid.UUID] = None
    material: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=64)
    finish: Optional[str] = Field(default=None, max_length=64)
    dimensions: Optional[dict[str, Any]] = None
    reorder_level: Optional[int] = Field(default=None, ge=0)
    custom_data: Optional[dict[str, Any]] = None
    is_best_seller: Optional[bool] = None
    is_active: Optional[bool] = None


class InventoryItemOut(TimestampedOrgScopedOut):

    id: uuid.UUID
    catalog_item_id: Optional[uuid.UUID]
    warehouse_id: uuid.UUID
    sku: str
    material: Optional[str]
    color: Optional[str]
    finish: Optional[str]
    dimensions: dict[str, Any]
    qty_on_hand: int
    qty_reserved: int
    reorder_level: int
    last_received_at: Optional[datetime]
    custom_data: dict[str, Any]
    cover_url: Optional[str]
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
    category: Optional[str] = Field(default=None, max_length=64)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    description: Optional[str] = None

    # Inventory-side
    warehouse_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    material: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=64)
    finish: Optional[str] = Field(default=None, max_length=64)
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
        description=(
            "Positive for receipt/dispatch/transfer; signed for adjust."
        ),
    )
    reference_type: Optional[str] = Field(default=None, max_length=64)
    reference_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class MovementOut(ORMModel):

    id: uuid.UUID
    org_id: uuid.UUID
    item_id: uuid.UUID
    type: MovementType
    qty: int
    reference_type: Optional[str]
    reference_id: Optional[uuid.UUID]
    notes: Optional[str]
    user_id: Optional[uuid.UUID]
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
    closed_at: Optional[datetime]


class StockAlertPatch(BaseModel):
    status: AlertStatus
