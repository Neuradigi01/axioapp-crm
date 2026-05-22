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
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from src.app.core.leads.imports.models import LeadImportStatus


SourcePlatform = Literal[
    "zoho",
    "hubspot",
    "salesforce",
    "freshsales",
    "generic_csv",
    "custom",
]


class LeadImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    uploaded_by: uuid.UUID
    name: str
    source_platform: str
    original_filename: str
    storage_path: str
    byte_size: int
    row_count_estimate: int
    mime_type: str
    status: LeadImportStatus
    mapping: Optional[dict[str, Any]] = None
    counts: Optional[dict[str, Any]] = None
    error_report_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LeadImportListResponse(BaseModel):
    items: list[LeadImportRead]
    total: int
    page: int
    size: int


__all__ = ["LeadImportRead", "LeadImportListResponse", "SourcePlatform"]
