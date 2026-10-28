"""`StandardFieldOverride` — per-org overrides for canonical form fields.

Parallel surface to `CustomFieldDefinition` (which lets an org *add*
columns). This table stores per-org overrides for the *standard*
columns (label, required, hidden, min/max, display order) declared
in `core.standard_fields.registry`.

Tenant-scoped via `TenantScoped` (auto-injected `org_id` + ORM filter +
RLS policy in migration 0039). One row per `(org_id, entity, field_key)`
— NULL in any override column means "inherit registry default."
"""

from __future__ import annotations

import decimal
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class StandardFieldOverride(Base, TenantScoped):
    __tablename__ = "tbl_standard_field_overrides"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "entity",
            "field_key",
            name="uq_standard_field_overrides_org_entity_field",
        ),
        Index("ix_sfo_org_entity", "org_id", "entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)

    # NULL = inherit registry default.
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    placeholder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    min_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    step_value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
