"""Pydantic v2 schemas for the catalog module.

`sku` is normalized to upper-case-trimmed on the wire so two operators
can't accidentally create two rows differing only by case
(`SOF001` vs `sof001`). `currency` defaults to `INR` at the DB level;
schemas keep it optional to match.

Extended by the catalog review (migration 0163):
  * ``description`` / ``cost_price`` / ``tags`` / ``image_urls`` /
    ``category_id`` on the item shapes.
  * ``CatalogCategoryCreate`` / ``Update`` / ``Out`` for the new
    per-org category entity.
  * ``CatalogItemBulkImportRow`` / ``CatalogItemBulkImportResult`` for
    the bulk-import endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.core.catalog.constants import CatalogStatus
from src.app.shared.schemas import TimestampedOrgScopedOut

_SKU_MAX = 64
_NAME_MAX = 255
_CATEGORY_MAX = 64


class CatalogItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=_SKU_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str | None = None
    category: str | None = Field(default=None, max_length=_CATEGORY_MAX)
    category_id: uuid.UUID | None = None
    price: Decimal = Field(ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    is_active: bool = True
    tags: list[str] = Field(default_factory=list)
    custom_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("sku")
    @classmethod
    def _normalize_sku(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in value:
            trimmed = t.strip()
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                out.append(trimmed)
        return out


class CatalogItemUpdate(BaseModel):
    """Partial update. `sku` is intentionally not editable — SKU is a
    stable identifier other tables (and stickers / barcodes IRL) bind
    to. Delete + recreate if you must change it."""

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    description: str | None = None
    category: str | None = Field(default=None, max_length=_CATEGORY_MAX)
    category_id: uuid.UUID | None = None
    price: Decimal | None = Field(default=None, ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    tags: list[str] | None = None
    custom_data: dict[str, Any] | None = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        out: list[str] = []
        for t in value:
            trimmed = t.strip()
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                out.append(trimmed)
        return out


class CatalogItemOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    sku: str
    name: str
    description: str | None = None
    category: str | None
    category_id: uuid.UUID | None = None
    price: Decimal
    cost_price: Decimal | None = None
    currency: str
    is_active: bool
    status: str
    published_at: datetime | None = None
    archived_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    custom_data: dict[str, Any]


class CatalogListResponse(BaseModel):
    """Pagination envelope for ``GET /api/v1/catalog``.

    Carries a ``status_counts`` histogram so the tab bar can render
    its counts without a second round-trip. Field shape kept identical
    to the previous ``PaginatedResponse[CatalogItemOut]`` alias for
    backwards compatibility with existing frontend readers."""

    items: list[CatalogItemOut]
    total: int
    page: int
    size: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class CatalogListFilters(BaseModel):
    """Query-string filters for ``GET /api/v1/catalog``. The router
    still accepts each field individually — this shape is what the
    service consumes internally."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = None
    active_only: bool = False
    statuses: list[CatalogStatus] | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200)


# --- Category schemas ------------------------------------------------------


class CatalogCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    icon_emoji: str | None = Field(default=None, max_length=8)
    color_hex: str | None = Field(default=None, min_length=7, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    display_order: int = 0
    is_active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True)


class CatalogCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    icon_emoji: str | None = Field(default=None, max_length=8)
    color_hex: str | None = Field(default=None, min_length=7, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    display_order: int | None = None
    is_active: bool | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class CatalogCategoryOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    icon_emoji: str | None
    color_hex: str | None
    display_order: int
    is_active: bool


# --- Bulk import (C8) -----------------------------------------------------


class CatalogItemBulkImportRow(BaseModel):
    """One row in a bulk import request. Same field constraints as
    `CatalogItemCreate` but grouped so the endpoint can report per-row
    failures alongside successes."""

    sku: str = Field(min_length=1, max_length=_SKU_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str | None = None
    category: str | None = Field(default=None, max_length=_CATEGORY_MAX)
    price: Decimal = Field(ge=0)
    cost_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    is_active: bool = True
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("sku")
    @classmethod
    def _normalize_sku(cls, value: str) -> str:
        return value.strip().upper()


class CatalogItemBulkImportRequest(BaseModel):
    """Bulk-import wrapper. `dry_run=True` validates + returns the
    counts without inserting; the frontend wizard uses that for the
    preview step."""

    rows: list[CatalogItemBulkImportRow] = Field(min_length=1, max_length=1000)
    dry_run: bool = False


class CatalogItemBulkImportRowError(BaseModel):
    """One rejected import row's forensic record.

    Existing consumers read `row_index` + `sku` + `reason` only;
    `column` + `value` were added when the shared per-field validators
    landed in the row loop, so operators can see *which* column tripped
    and *what* the offending value was without downloading the CSV.
    Both remain optional to keep the payload additive for older UI builds.
    """

    row_index: int
    sku: str
    reason: str
    column: str | None = None
    value: str | None = None


class CatalogItemBulkImportResult(BaseModel):
    """`inserted` — rows successfully created. `skipped` — rows whose
    SKU already exists in the org (bulk-import intentionally does NOT
    overwrite; use the individual PATCH endpoint for that). `errors`
    — malformed rows (missing name / invalid price / etc.)."""

    inserted: int
    skipped: int
    errors: list[CatalogItemBulkImportRowError]
    dry_run: bool


# --- Public (unauthenticated) shapes --------------------------------------
#
# Never carry the item's UUID or the org's UUID — the Fernet token in
# the URL is the only stable identifier a customer should ever see.


class PublicCatalogCardOut(BaseModel):
    """Grid card for ``GET /api/public/catalog?org=<slug>``.

    Trimmed to what the customer-facing grid renders: name / SKU /
    price / category + featured image + the shareable URL. No UUIDs,
    no timestamps, no ``is_active`` (published only)."""

    name: str
    sku: str
    category: str | None = None
    price: Decimal
    currency: str
    short_description: str | None = None
    tags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    public_url: str


class PublicCatalogDetailOut(BaseModel):
    """Detail page for ``GET /api/public/catalog/{token}``. Full
    customer-safe field set + ordered gallery. Still no UUIDs."""

    name: str
    sku: str
    description: str | None = None
    category: str | None = None
    price: Decimal
    currency: str
    tags: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)


class PublicUrlOut(BaseModel):
    """Response for the owner-side "get shareable URL" endpoint."""

    url: str
    token: str
