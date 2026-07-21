"""Pydantic v2 schemas for the lead-imports sub-package.

`SourcePlatform` is the API contract for the upload endpoint's
`source_platform` form field — the fixed enum of CRMs the customer
might be migrating from. The matching presets table (Step 3) seeds one
row per known platform.

`LeadImportRead` is the response shape for `POST /upload`, `GET /` and
`GET /{id}`. All response fields come straight off the model with no
extra projection — the `mapping` / `counts` / `error_report_path`
columns are NULL at this step and surface as null until the Step 2/3
flows populate them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.leads.imports.models import LeadImportStatus
from src.app.shared.schemas import ORMModel, PaginatedResponse, TimestampedOrgScopedOut

SourcePlatform = Literal[
    "zoho",
    "hubspot",
    "salesforce",
    "freshsales",
    "generic_csv",
    "custom",
]


class LeadImportRead(TimestampedOrgScopedOut):
    id: uuid.UUID
    uploaded_by: uuid.UUID
    name: str
    source_platform: str
    original_filename: str
    storage_path: str
    byte_size: int
    row_count_estimate: int
    mime_type: str
    status: LeadImportStatus
    mapping: dict[str, Any] | None = None
    counts: dict[str, Any] | None = None
    error_report_path: str | None = None
    skipped_report_path: str | None = None


LeadImportListResponse = PaginatedResponse[LeadImportRead]


class LeadImportCommit(BaseModel):
    """Request body for `POST /leads/import/{id}/commit`.

    `mapping` is `{csv_column_name: crm_field_key | None}`. Mapping a
    column to None (or omitting it) means "ignore this column". Every
    non-null value is validated against the whitelist of allowed
    targets — see `service._ALLOWED_TARGETS`. Mapping must cover
    `contact.full_name` (the only required field) — the row otherwise
    cannot create a contact.
    """

    mapping: dict[str, str | None] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class PresetCreate(BaseModel):
    """Request body for `POST /leads/import/presets`.

    `name` is optional — service auto-fills "<source_platform> v<N>"
    if omitted. `mapping` is the same shape as `LeadImportCommit.mapping`
    and is validated against the same target whitelist.
    """

    name: str | None = Field(default=None, max_length=128)
    source_platform: SourcePlatform
    mapping: dict[str, str | None] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class PresetRead(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID | None  # None for system presets
    source_platform: str
    name: str
    mapping: dict[str, str | None]
    is_system: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MappingTarget(BaseModel):
    """One row in the `/leads/import/targets` response.

    Frontend renders these as the options inside each per-column
    mapping dropdown. `custom` lets the UI group standard vs. custom
    targets visually.
    """

    key: str  # e.g. "contact.full_name" or "custom_data.industry"
    label: str  # human label, e.g. "Full name"
    field_type: str  # "text" / "tel" / "email" / "number" / ...
    required: bool  # backend-required (cannot be omitted)
    custom: bool  # True for `custom_data.<key>`, False for canonical


class PreviewResponse(BaseModel):
    """Response for `GET /leads/import/{id}/preview?limit=N`.

    `columns` is the file's header row (original column order, preserved
    so the mapping UI can align dropdowns to the source columns one-to-
    one). `rows` is the first N data rows as `string | null` cell
    values — Pydantic / lead-create downstream does the type coercion.
    """

    columns: list[str]
    rows: list[list[str | None]]


__all__ = [
    "LeadImportCommit",
    "LeadImportListResponse",
    "LeadImportRead",
    "MappingTarget",
    "PresetCreate",
    "PresetRead",
    "PreviewResponse",
    "SourcePlatform",
]
