"""Pydantic v2 schemas for the catalog module.

`sku` is normalized to upper-case-trimmed on the wire so two operators
can't accidentally create two rows differing only by case
(`SOF001` vs `sof001`). `currency` defaults to `INR` at the DB level;
schemas keep it optional to match.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.shared.schemas import PaginatedResponse, TimestampedOrgScopedOut

_SKU_MAX = 64
_NAME_MAX = 255
_CATEGORY_MAX = 64


class CatalogItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=_SKU_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    category: str | None = Field(default=None, max_length=_CATEGORY_MAX)
    price: Decimal = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    is_active: bool = True
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


class CatalogItemUpdate(BaseModel):
    """Partial update. `sku` is intentionally not editable — SKU is a
    stable identifier other tables (and stickers / barcodes IRL) bind
    to. Delete + recreate if you must change it."""

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    category: str | None = Field(default=None, max_length=_CATEGORY_MAX)
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    custom_data: dict[str, Any] | None = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class CatalogItemOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    sku: str
    name: str
    category: str | None
    price: Decimal
    currency: str
    is_active: bool
    image_url: str | None = None
    custom_data: dict[str, Any]


CatalogListResponse = PaginatedResponse[CatalogItemOut]
