"""Pydantic v2 schemas for the catalog module.

`sku` is normalized to upper-case-trimmed on the wire so two operators
can't accidentally create two rows differing only by case
(`SOF001` vs `sof001`). `currency` defaults to `INR` at the DB level;
schemas keep it optional to match.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.shared.schemas import PaginatedResponse


_SKU_MAX = 64
_NAME_MAX = 255
_CATEGORY_MAX = 64


class CatalogItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=_SKU_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    category: Optional[str] = Field(default=None, max_length=_CATEGORY_MAX)
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

    name: Optional[str] = Field(default=None, min_length=1, max_length=_NAME_MAX)
    category: Optional[str] = Field(default=None, max_length=_CATEGORY_MAX)
    price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    is_active: Optional[bool] = None
    custom_data: Optional[dict[str, Any]] = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value is not None else None


class CatalogItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    sku: str
    name: str
    category: Optional[str]
    price: Decimal
    currency: str
    is_active: bool
    custom_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


CatalogListResponse = PaginatedResponse[CatalogItemOut]
