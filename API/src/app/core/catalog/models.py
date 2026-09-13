"""Catalog ORM models — item + category.

`CatalogItem` is the bare-minimum core product row. Phase 3 ships the
universal CRM "what product is this contact / lead / walk-in interested
in?" lookup. The furniture pack (Phase 4) bolts a richer
`fp_inventory_items` table on top with stock movements, images,
multi-location, etc. — keep this model intentionally thin.

`CatalogCategory` (added by migration 0163) replaces the previous
free-text ``CatalogItem.category`` column with a first-class per-org
entity so operators can rename / colour / order / manage categories
without stringly-typed drift. The free-text ``category`` column is
kept as a read-only display fallback across upgrade + downgrade so
callers that still reference it don't break. Frontend writes always
go through ``category_id``.

Tenant-scoped (RLS on, ORM filter applied). `sku` is unique per org
so the same SKU can mean different things in two different stores.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CatalogCategory(Base, TenantScoped):
    """Per-org catalog category. Migration 0163."""

    __tablename__ = "tbl_catalog_categories"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_catalog_categories_org_name"),
        Index("ix_catalog_categories_org_order", "org_id", "display_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
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


class CatalogItem(Base, TenantScoped):
    __tablename__ = "tbl_catalog_items"
    __table_args__ = (
        UniqueConstraint("org_id", "sku", name="uq_catalog_items_org_sku"),
        Index("ix_catalog_items_org_category", "org_id", "category"),
        Index("ix_catalog_items_org_status", "org_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # C4 — long-form product notes (migration 0163). Rendered as a
    # description textarea in the modal + shown on the view modal.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text category name kept for backwards compat / display
    # fallback; new writes go through category_id below. Old rows
    # populated by migration 0163 backfill still resolve.
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # C2 — first-class category FK (migration 0163). Nullable so items
    # without a category still validate; ON DELETE SET NULL so deleting
    # a category unlinks items rather than cascading.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_catalog_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # C6 — cost price for margin analytics (migration 0163). Nullable
    # because not every org tracks cost; renderers show "—" when unset.
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'INR'"))
    # C13 — free-form labels (migration 0163). Postgres TEXT[] so
    # filters can use ANY() / && without a bridge table.
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Publish state machine (migration 0223). Kept as plain VARCHAR;
    # values validated against ``CatalogStatus`` at the service layer.
    # ``is_active`` continues to govern whether the item shows in
    # internal pickers (lead-interest, walk-in etc.); ``status`` gates
    # the public share surface.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'draft'"),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Primary cover image. Kept as a scalar for backwards compat and
    # because most cards render only one image; the gallery below is
    # additive.
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # C5 — gallery beyond the primary cover (migration 0163). Order
    # matters — first entry is the second-most-important image.
    image_urls: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
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
