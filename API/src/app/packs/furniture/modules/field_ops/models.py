"""Furniture-pack: Field Operations models.

Two `fp_*` tables, both TenantScoped + RLS-on:

- `FieldVisit` — one site visit. The scheduling side reuses the core
  `appointments` engine (FK → `appointments`); this row carries the
  pack-specific fields (purpose, link to a custom order, signature
  URL, completion timestamp).
- `FieldVisitPhoto` — visit photos uploaded via `StorageBackend`.

`purpose` is an ENUM, distinct from `appointments.purpose` (which is
free-text). Field visits have a closed set of types for analytics.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class FieldVisitPurpose(str, enum.Enum):
    measurement = "measurement"
    installation = "installation"
    inspection = "inspection"


field_visit_purpose_enum = ENUM(
    FieldVisitPurpose,
    name="fp_field_visit_purpose",
    values_callable=lambda obj: [m.value for m in obj],
)


class FieldVisit(Base, TenantScoped):
    __tablename__ = "tbl_fp_field_visits"
    __table_args__ = (
        Index("ix_fp_field_visits_appointment", "appointment_id"),
        Index("ix_fp_field_visits_custom_order", "custom_order_id"),
        Index("ix_fp_field_visits_org_completed", "org_id", "completed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_appointments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    purpose: Mapped[FieldVisitPurpose] = mapped_column(
        field_visit_purpose_enum, nullable=False
    )
    custom_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_fp_custom_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signature_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
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


class FieldVisitPhoto(Base, TenantScoped):
    __tablename__ = "tbl_fp_field_visit_photos"
    __table_args__ = (
        Index("ix_fp_field_visit_photos_visit", "visit_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_fp_field_visits.id", ondelete="CASCADE"),
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
