"""Real-estate-pack Property models.

Two tables, both `tbl_rp_*` prefixed (Real-estate Pack — analogous to
Furniture's `tbl_fp_*`) and `TenantScoped` (so RLS + the ORM-level
tenant filter both fire):

- `Property` (`tbl_rp_properties`) — one row per real-estate listing
  the org manages. Carries the structured fields the requirements
  doc lists (title, type, category, price, address, bedrooms,
  bathrooms, area, amenities, contact info) plus a `status` state
  machine (`draft` → `published`/`unpublished` → `archived`/`sold`).
- `PropertyImage` (`tbl_rp_property_images`) — gallery images. Files
  live on the filesystem under `./storage/{org_id}/property/{property_id}/`
  via the shared storage backend; only path + metadata land in the
  DB. Partial unique index enforces at-most-one `is_featured=true`
  per property.

Both tables are tenant-isolated via `TenantScoped.org_id` (auto-injected
into ORM SELECTs) and Postgres RLS (belt in the migration). The public
listing / detail endpoints (Step 5) set `app.org_id` from the decoded
Fernet token so the same policy authorises the unauthenticated path.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class Property(Base, TenantScoped):
    """A real-estate listing. Status is a plain string validated at
    the service layer against `PropertyStatus`; keeping it out of a
    Postgres ENUM makes future state additions a one-liner rather
    than an `ALTER TYPE` migration."""

    __tablename__ = "tbl_rp_properties"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_rp_properties_org_slug"),
        Index(
            "ix_rp_properties_org_status_created",
            "org_id",
            "status",
            "created_at",
        ),
        Index("ix_rp_properties_org_city_type", "org_id", "city", "property_type"),
        CheckConstraint("length(title) >= 3", name="ck_rp_properties_title_min_len"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # Creator / owner within the org. No FK — bare UUID (matches the
    # rest of the pack modules; user deletion is handled at the
    # service layer, not by DB cascade).
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # ------- Core identifying fields --------------------------------
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Machine-generated from title on insert, unique per org. Used by
    # internal admin analytics; the public URL uses a Fernet token
    # (Step 5), not the slug.
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------- Classification (validated against enums at service) ----
    property_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    # ------- Money ----------------------------------------------------
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=sql_text("'INR'")
    )

    # ------- Location -------------------------------------------------
    address_line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ------- Physical details ----------------------------------------
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    area_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    area_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amenities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'[]'::jsonb"),
    )

    # ------- Contact --------------------------------------------------
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ------- Lifecycle ------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ------- Org-level custom fields (Rule 3) ------------------------
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
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

    # Eager gallery loading is opt-in per query via selectinload.
    images: Mapped[list["PropertyImage"]] = relationship(
        "PropertyImage",
        back_populates="property",
        cascade="all, delete-orphan",
        order_by="PropertyImage.display_order",
        lazy="raise_on_sql",
    )


class PropertyImage(Base, TenantScoped):
    """One row per uploaded property image. Physical file at
    `./storage/{org_id}/property/{property_id}/{image_id}.{ext}`."""

    __tablename__ = "tbl_rp_property_images"
    __table_args__ = (
        Index(
            "ix_rp_property_images_property_order",
            "property_id",
            "display_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_rp_properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )

    property: Mapped[Property] = relationship("Property", back_populates="images")


__all__ = ["Property", "PropertyImage"]
