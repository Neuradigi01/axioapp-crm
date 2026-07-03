"""Property module — Pydantic v2 schemas (skeleton).

Step 2 ships the read shapes needed by the DAL smoke tests. Full
request models (`PropertyCreate`, `PropertyUpdate`, list filters,
image upload / reorder) land in Steps 3–4 alongside the router.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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
    """Full property detail as returned by GETs. Extended by Step 3
    to include `featured_image_url` + `image_urls` (derived from
    the `images` relationship)."""

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


__all__ = ["PropertyImageOut", "PropertyOut"]
