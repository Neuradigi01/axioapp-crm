"""Furniture-pack inventory models.

Four tables, all `fp_*` prefixed (pack-namespaced) and TenantScoped:

- `Warehouse` (`fp_warehouses`) — physical store / godown. `is_default`
  flags the org's primary warehouse so the UI defaults landed-stock to
  it. Unique-per-org by name.
- `InventoryItem` (`fp_inventory_items`) — one row per (catalog item ×
  warehouse). Carries `qty_on_hand`, `qty_reserved`, `reorder_level`,
  plus furniture-specific attributes (material/colour/finish/JSONB
  dimensions). CHECK constraints enforce `qty_on_hand ≥ 0` and
  `qty_reserved ≤ qty_on_hand` at the DB level.
- `InventoryMovement` (`fp_inventory_movements`) — append-only ledger.
  Every receipt/dispatch/adjust/transfer is a row. The service layer
  ensures the matching qty mutation lives in the same transaction.
- `StockAlert` (`fp_inventory_alerts`) — open / ordered / closed.
  Re-computed automatically after every movement; the reorder
  workflow (Phase 4.5+) reads `severity='out'`+`priority='high'`.

This is the first Layer-2 (pack) module to touch the database.
The `fp_` prefix lets a `DROP DATABASE` cleanly separate platform
state from vertical-pack state in dev.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class MovementType(str, enum.Enum):
    receipt = "receipt"      # +qty, e.g. PO arrival
    dispatch = "dispatch"    # -qty, e.g. sale / delivery
    adjust = "adjust"        # +/-qty, e.g. damage / cycle count correction
    transfer = "transfer"    # -qty here (caller pairs with a receipt elsewhere)


class AlertSeverity(str, enum.Enum):
    low = "low"
    out = "out"


class AlertPriority(str, enum.Enum):
    low = "low"
    med = "med"
    high = "high"


class AlertStatus(str, enum.Enum):
    open = "open"
    ordered = "ordered"
    closed = "closed"


fp_movement_type_enum = ENUM(
    MovementType,
    name="fp_movement_type",
    values_callable=lambda obj: [m.value for m in obj],
)
fp_alert_severity_enum = ENUM(
    AlertSeverity,
    name="fp_alert_severity",
    values_callable=lambda obj: [m.value for m in obj],
)
fp_alert_priority_enum = ENUM(
    AlertPriority,
    name="fp_alert_priority",
    values_callable=lambda obj: [m.value for m in obj],
)
fp_alert_status_enum = ENUM(
    AlertStatus,
    name="fp_alert_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class Warehouse(Base, TenantScoped):
    __tablename__ = "fp_warehouses"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_fp_warehouses_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )


class InventoryItem(Base, TenantScoped):
    __tablename__ = "fp_inventory_items"
    __table_args__ = (
        CheckConstraint(
            "qty_on_hand >= 0",
            name="ck_fp_inventory_items_qty_on_hand_nonneg",
        ),
        CheckConstraint(
            "qty_reserved >= 0",
            name="ck_fp_inventory_items_qty_reserved_nonneg",
        ),
        CheckConstraint(
            "qty_reserved <= qty_on_hand",
            name="ck_fp_inventory_items_reserved_le_on_hand",
        ),
        CheckConstraint(
            "reorder_level >= 0",
            name="ck_fp_inventory_items_reorder_nonneg",
        ),
        UniqueConstraint(
            "org_id", "warehouse_id", "sku",
            name="uq_fp_inventory_items_warehouse_sku",
        ),
        Index("ix_fp_inventory_items_warehouse", "warehouse_id"),
        Index("ix_fp_inventory_items_catalog", "catalog_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fp_warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    material: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finish: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    qty_on_hand: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    qty_reserved: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    reorder_level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    last_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    is_best_seller: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )


class InventoryMovement(Base, TenantScoped):
    __tablename__ = "fp_inventory_movements"
    __table_args__ = (
        Index(
            "ix_fp_inventory_movements_item_created",
            "item_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fp_inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[MovementType] = mapped_column(
        fp_movement_type_enum, nullable=False
    )
    # Signed delta applied to `qty_on_hand`. The service computes the
    # sign from `type` so callers always pass a positive `qty`
    # (except `adjust`, which can be negative).
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class StockAlert(Base, TenantScoped):
    __tablename__ = "fp_inventory_alerts"
    __table_args__ = (
        Index(
            "ix_fp_inventory_alerts_item_status",
            "item_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fp_inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        fp_alert_severity_enum, nullable=False
    )
    priority: Mapped[AlertPriority] = mapped_column(
        fp_alert_priority_enum,
        nullable=False,
        server_default=sql_text("'med'"),
    )
    suggested_reorder_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    status: Mapped[AlertStatus] = mapped_column(
        fp_alert_status_enum,
        nullable=False,
        server_default=sql_text("'open'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
