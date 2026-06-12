"""Furniture-pack: Custom Orders models.

Four `fp_*` tables, all TenantScoped + RLS-on:

- `CustomOrder` — head of a bespoke build. `pipeline_stage` is the
  stage key from the `custom_orders` pipeline (seeded by the
  furniture pack in 4.2: measurement_scheduled → design_phase →
  in_production → qc → installation → delivered / cancelled).
- `CustomOrderMeasurement` — one row per physical dimension captured
  on a site visit.
- `CustomOrderPhoto` — site visit / progress photos uploaded via
  `StorageBackend` (URL persisted here).
- `CustomOrderStageHistory` — append-only ledger of stage transitions
  for funnel analytics. The pipeline engine also writes a
  `status_change` activity on the contact timeline; this table is
  the per-order audit trail.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CustomOrder(Base, TenantScoped):
    __tablename__ = "tbl_fp_custom_orders"
    __table_args__ = (
        Index("ix_fp_custom_orders_org_stage", "org_id", "pipeline_stage"),
        Index("ix_fp_custom_orders_contact", "contact_id"),
        Index("ix_fp_custom_orders_lead", "lead_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finish: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Stage key from the `custom_orders` pipeline. Free text (the
    # pipelines engine validates against the registered pipeline at
    # move time) so a stale stage key on a row doesn't break selects.
    pipeline_stage: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=sql_text("'measurement_scheduled'")
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    expected_delivery_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    advance_paid: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
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


class CustomOrderMeasurement(Base, TenantScoped):
    __tablename__ = "tbl_fp_custom_order_measurements"
    __table_args__ = (
        Index("ix_fp_custom_order_measurements_order", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_fp_custom_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_label: Mapped[str] = mapped_column(String(128), nullable=False)
    length_cm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    width_cm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    height_cm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class CustomOrderPhoto(Base, TenantScoped):
    __tablename__ = "tbl_fp_custom_order_photos"
    __table_args__ = (
        Index("ix_fp_custom_order_photos_order", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_fp_custom_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class CustomOrderStageHistory(Base, TenantScoped):
    __tablename__ = "tbl_fp_custom_order_stages"
    __table_args__ = (
        Index(
            "ix_fp_custom_order_stages_order_changed",
            "order_id",
            "changed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_fp_custom_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_stage: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    to_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
