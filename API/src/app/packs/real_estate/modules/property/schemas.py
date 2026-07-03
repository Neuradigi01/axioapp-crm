"""Property module — Pydantic v2 schemas.

Request models (`PropertyCreate` / `PropertyUpdate` / `PropertyListFilters`)
and response envelopes (`PropertyOut` / `PropertyListOut` /
`PropertyImageOut`). Enum-shaped fields validate against the pack's
string enums in `constants.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.packs.real_estate.modules.property.constants import (
    PropertyCategory,
    PropertyStatus,
    PropertyType,
)


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class PropertyImageOut(BaseModel):
    """Single image in a property gallery."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    image_url: str | None = None
    image_path: str
    display_order: int
    is_featured: bool
    created_at: datetime


class PropertyOut(BaseModel):
    """Full property detail as returned by GETs.

    ``images`` is empty by default. Endpoints that eager-load the
    gallery set it; endpoints that page through a large list skip it
    and populate ``featured_image_url`` / ``image_urls`` from the
    property's images relationship (populated via ``selectinload``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    owner_id: uuid.UUID

    title: str
    slug: str
    description: str | None = None

    property_type: str
    category: str

    price: Decimal | None = None
    currency: str

    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    pincode: str | None = None

    bedrooms: int | None = None
    bathrooms: int | None = None
    area_value: Decimal | None = None
    area_unit: str | None = None
    amenities: list[str] = Field(default_factory=list)

    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None

    status: str
    published_at: datetime | None = None
    archived_at: datetime | None = None
    sold_at: datetime | None = None

    custom_data: dict = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

    images: list[PropertyImageOut] = Field(default_factory=list)
    featured_image_url: str | None = None


class PropertyListOut(BaseModel):
    """Pagination envelope for the owner-dashboard list."""

    items: list[PropertyOut]
    total: int
    page: int
    page_size: int
    status_counts: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Request shapes
# ---------------------------------------------------------------------------


class PropertyCreate(BaseModel):
    """Body for ``POST /api/v1/property``. Only title, type, category
    are required; everything else is optional and can be filled in via
    ``PATCH`` before publishing."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=3, max_length=200)
    property_type: PropertyType
    category: PropertyCategory

    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    address_line: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    pincode: str | None = Field(default=None, max_length=20)

    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    area_value: Decimal | None = Field(default=None, ge=0)
    area_unit: str | None = Field(default=None, max_length=20)
    amenities: list[str] = Field(default_factory=list)

    contact_person: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=200)

    custom_data: dict = Field(default_factory=dict)


class PropertyUpdate(BaseModel):
    """Body for ``PATCH /api/v1/property/{id}``. Every field optional
    — only present fields are applied. Passing ``None`` explicitly is
    allowed for nullable columns (e.g. clear the description)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=200)
    property_type: PropertyType | None = None
    category: PropertyCategory | None = None

    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    address_line: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    pincode: str | None = Field(default=None, max_length=20)

    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)
    area_value: Decimal | None = Field(default=None, ge=0)
    area_unit: str | None = Field(default=None, max_length=20)
    amenities: list[str] | None = None

    contact_person: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=200)

    custom_data: dict | None = None


class PropertyListFilters(BaseModel):
    """Query-string filters for ``GET /api/v1/property``."""

    model_config = ConfigDict(extra="forbid")

    statuses: list[PropertyStatus] | None = None
    property_type: PropertyType | None = None
    category: PropertyCategory | None = None
    city: str | None = None
    search: str | None = None
    owner_id: uuid.UUID | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    sort_by: str = "created_at"
    sort_desc: bool = True
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("sort_by")
    @classmethod
    def _restrict_sort_column(cls, v: str) -> str:
        allowed = {"created_at", "updated_at", "price", "title"}
        if v not in allowed:
            raise ValueError(f"sort_by must be one of {sorted(allowed)}")
        return v


__all__ = [
    "PropertyCreate",
    "PropertyImageOut",
    "PropertyListFilters",
    "PropertyListOut",
    "PropertyOut",
    "PropertyUpdate",
]
