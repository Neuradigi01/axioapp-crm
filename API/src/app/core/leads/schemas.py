"""Pydantic v2 schemas for the leads module.

`pipeline_stage` is optional on create — when omitted the service uses
the first stage of the `leads` pipeline (sorted by `display_order`).
`status` is server-managed; the HTTP surface never accepts an explicit
status on create or update because it's auto-synced with the stage's
is_won/is_lost flags via the move-stage endpoint.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.leads.models import LeadSource, LeadStatus


class LeadCreate(BaseModel):
    contact_id: uuid.UUID
    pipeline_stage: Optional[str] = Field(default=None, max_length=64)
    assigned_to_id: Optional[uuid.UUID] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    expected_close_date: Optional[date] = None
    custom_data: dict[str, Any] = Field(default_factory=dict)
    source: LeadSource = LeadSource.manual
    # Channel-supplied provenance (widget UTM, ad webhook ids, etc.).
    # Stays None for manual + bulk-import paths.
    attribution: Optional[dict[str, Any]] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadUpdate(BaseModel):
    """Partial update. `pipeline_stage` and `status` are NOT here on
    purpose — stage changes go through the move-stage endpoint so the
    pipeline engine logs activity + audit and keeps status in sync.
    """

    contact_id: Optional[uuid.UUID] = None
    assigned_to_id: Optional[uuid.UUID] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    expected_close_date: Optional[date] = None
    custom_data: Optional[dict[str, Any]] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class MoveStageRequest(BaseModel):
    to_stage: str = Field(min_length=1, max_length=64)

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    contact_id: uuid.UUID
    pipeline_stage: str
    status: LeadStatus
    source: LeadSource
    assigned_to_id: Optional[uuid.UUID]
    budget: Optional[Decimal]
    expected_close_date: Optional[date]
    custom_data: dict[str, Any]
    attribution: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    size: int
