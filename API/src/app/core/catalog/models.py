"""`CatalogItem` — bare-minimum core catalog row.

Phase 3 ships the universal CRM "what product is this contact / lead /
walk-in interested in?" lookup. The furniture pack (Phase 4) bolts a
richer `fp_inventory_items` table on top with stock movements, images,
multi-location, etc. — keep this model intentionally thin.

Tenant-scoped (RLS on, ORM filter applied). `sku` is unique per org
so the same SKU can mean different things in two different stores.
Indexed for the two hot reads: `(org_id, category)` for the category
filter, and a btree on `(org_id, sku)` for picker autocomplete.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CatalogItem(Base, TenantScoped):
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("org_id", "sku", name="uq_catalog_items_org_sku"),
        Index("ix_catalog_items_org_category", "org_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'INR'")
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
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
