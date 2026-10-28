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

from src.app.shared.schemas import (
    BulkAddTag,
    BulkAddTagResult,
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
    ORMModel,
    PaginatedResponse,
    TimestampedOrgScopedOut,
)

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


class ContactOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    notes: str | None
    custom_data: dict[str, Any]
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
    # whatsapp-platform-upgrade Step 22 — DPDP opt-in state.
    whatsapp_opt_in_status: str = "never_contacted"
    whatsapp_opt_in_source: str | None = None
    whatsapp_opt_in_recorded_at: datetime | None = None
    whatsapp_opt_in_recorded_by_user_id: uuid.UUID | None = None
    whatsapp_opt_out_recorded_at: datetime | None = None
    whatsapp_opt_out_reason: str | None = None


class ContactListItem(ORMModel):
    """Slim shape for list endpoints — no notes, no custom_data."""

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    source: str | None
    tags: list[str]
    assigned_to_id: uuid.UUID | None
    last_activity_at: datetime | None
    created_at: datetime
    # Step 22 — chip on the list page.
    whatsapp_opt_in_status: str = "never_contacted"


# --- Step 22 opt-in request / response shapes ------------------------------


class OptInRecordRequest(BaseModel):
    """Body of ``POST /contacts/{id}/opt-in``."""

    source: str = Field(
        description="Where this opt-in was captured. One of "
        "form_widget / bulk_import / manual_entry / "
        "inbound_first_message / explicit_opt_in_link."
    )
    reason: str | None = Field(default=None, max_length=500)
    request_evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OptOutRecordRequest(BaseModel):
    """Body of ``POST /contacts/{id}/opt-out``."""

    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Optional free-text justification (e.g. 'customer requested by phone').",
    )
    request_evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConsentEventOut(ORMModel):
    """One row from the immutable consent log."""

    id: uuid.UUID
    channel: str
    old_status: str | None
    new_status: str
    source: str | None
    actor_user_id: uuid.UUID | None
    ip_address: str | None
    reason: str | None
    recorded_at: datetime


class OptInHistoryOut(BaseModel):
    """Combined "where are we + how did we get here" payload for the
    contact-detail opt-in panel."""

    contact_id: uuid.UUID
    status: str
    source: str | None
    recorded_at: datetime | None
    recorded_by_user_id: uuid.UUID | None
    opt_out_recorded_at: datetime | None
    opt_out_reason: str | None
    events: list[ConsentEventOut]


ContactListResponse = PaginatedResponse[ContactListItem]


# --- Reassign / bulk-action request and response shapes ---------------------


class ContactReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    # Free-form note saved on the audit activity payload. Optional.
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


ContactBulkReassign = BulkReassign
ContactBulkDelete = BulkDelete
ContactBulkAddTag = BulkAddTag

ContactBulkReassignResult = BulkReassignResult
ContactBulkDeleteResult = BulkDeleteResult
ContactBulkAddTagResult = BulkAddTagResult


# --- Duplicate-check response shape -----------------------------------------


class ContactDuplicateMatch(ORMModel):
    """One existing row that matched the create-modal's dup check.

    Slim shape (`id` + name + phone + email) so the FE can render a
    yellow banner with a "view" link without an extra round-trip.
    """

    id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None


class ContactDuplicateCheckResponse(BaseModel):
    matches: list[ContactDuplicateMatch]
