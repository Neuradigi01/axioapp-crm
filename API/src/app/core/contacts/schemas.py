"""Pydantic v2 schemas for the contacts module.

`custom_data` is intentionally typed as ``dict[str, Any]``: deep
validation against the per-org `custom_field_definitions` happens in
the service layer (``validate_custom_data``), not at the Pydantic
boundary. The router's auto-422 only catches the shape issues that
are independent of tenant data — type-of-each-key cannot be expressed
statically here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


_TAG_MAX = 64
_TAG_COUNT_MAX = 32


class ContactCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=_TAG_COUNT_MAX)
    notes: str | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)

    def cleaned_tags(self) -> list[str]:
        # Stable order, no duplicates, no empties, length cap honoured.
        seen: dict[str, None] = {}
        for tag in self.tags:
            value = tag.strip()
            if 0 < len(value) <= _TAG_MAX and value not in seen:
                seen[value] = None
        return list(seen)


class ContactUpdate(BaseModel):
    """Every field optional. `custom_data` REPLACES (not merges) the JSONB."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=_TAG_COUNT_MAX)
    notes: str | None = None
    custom_data: dict[str, Any] | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    notes: str | None
    custom_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ContactListItem(BaseModel):
    """Slim shape for list endpoints — no notes, no custom_data."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    created_at: datetime


class ContactListResponse(BaseModel):
    items: list[ContactListItem]
    total: int
    page: int
    size: int
