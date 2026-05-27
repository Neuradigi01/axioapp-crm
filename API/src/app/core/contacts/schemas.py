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
    assigned_to_id: uuid.UUID | None = None

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
    """Every field optional. `custom_data` REPLACES (not merges) the JSONB.

    `last_activity_at` is intentionally absent — server-managed by the
    activities-service insert hook; never accepted from the client.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = Field(default=None, max_length=_TAG_COUNT_MAX)
    notes: str | None = None
    custom_data: dict[str, Any] | None = None
    assigned_to_id: uuid.UUID | None = None

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
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
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
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
    created_at: datetime


class ContactListResponse(BaseModel):
    items: list[ContactListItem]
    total: int
    page: int
    size: int


# --- Reassign / bulk-action request and response shapes ---------------------


class ContactReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    # Free-form note saved on the audit activity payload. Optional.
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class ContactBulkReassign(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class ContactBulkDelete(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class ContactBulkAddTag(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    tag: str = Field(min_length=1, max_length=_TAG_MAX)

    model_config = ConfigDict(str_strip_whitespace=True)


class ContactBulkReassignResult(BaseModel):
    reassigned: int


class ContactBulkDeleteResult(BaseModel):
    deleted: int


class ContactBulkAddTagResult(BaseModel):
    updated: int


# --- Duplicate-check response shape -----------------------------------------


class ContactDuplicateMatch(BaseModel):
    """One existing row that matched the create-modal's dup check.

    Slim shape (`id` + name + phone + email) so the FE can render a
    yellow banner with a "view" link without an extra round-trip.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None


class ContactDuplicateCheckResponse(BaseModel):
    matches: list[ContactDuplicateMatch]
