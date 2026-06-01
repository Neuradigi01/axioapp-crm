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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.leads.models import LeadSource, LeadStatus


# Picklist for the lost-reason field. Pinned both here (Pydantic
# rejection at the API edge) and in the `ck_leads_lost_reason_picklist`
# CHECK constraint (migration 0054) so a malformed value can't slip in
# via raw SQL either.
LOST_REASONS: tuple[str, ...] = (
    "price",
    "timing",
    "competitor",
    "no_response",
    "other",
)


def _validate_lost_reason_pair(
    lost_reason: str | None, lost_reason_other: str | None
) -> None:
    """Shared validator: `lost_reason` must be in the picklist; when
    `lost_reason == 'other'`, the free-text `lost_reason_other` must
    be non-empty."""
    if lost_reason is not None and lost_reason not in LOST_REASONS:
        raise ValueError(
            f"lost_reason must be one of {LOST_REASONS}; got {lost_reason!r}"
        )
    if lost_reason == "other" and not (lost_reason_other and lost_reason_other.strip()):
        raise ValueError(
            "lost_reason_other is required when lost_reason='other'"
        )


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

    `lost_reason` + `lost_reason_other` ARE accepted so a follow-up
    edit can refine the reason after the initial Lost transition; the
    validators run regardless of how the row arrived at `lost`.
    """

    contact_id: Optional[uuid.UUID] = None
    assigned_to_id: Optional[uuid.UUID] = None
    budget: Optional[Decimal] = Field(default=None, ge=0)
    expected_close_date: Optional[date] = None
    custom_data: Optional[dict[str, Any]] = None
    lost_reason: Optional[str] = Field(default=None, max_length=32)
    lost_reason_other: Optional[str] = Field(default=None, max_length=255)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_lost_reason(self) -> "LeadUpdate":
        _validate_lost_reason_pair(self.lost_reason, self.lost_reason_other)
        return self


class MoveStageRequest(BaseModel):
    """Move-stage request. When the destination stage has `is_lost=true`
    the service requires `lost_reason` (picklist) — the FE collects it
    in the move-to-Lost modal and submits it here in the same call.
    """

    to_stage: str = Field(min_length=1, max_length=64)
    lost_reason: Optional[str] = Field(default=None, max_length=32)
    lost_reason_other: Optional[str] = Field(default=None, max_length=255)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_lost_reason(self) -> "MoveStageRequest":
        _validate_lost_reason_pair(self.lost_reason, self.lost_reason_other)
        return self


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
    # Rule-engine output, ``[0, 100]``. Computed by
    # ``src.app.core.leads.scoring`` after every create / update that
    # touches a rule-relevant column. The hourly Celery sweep keeps the
    # value fresh when rules themselves change.
    lead_score: int = 0
    custom_data: dict[str, Any]
    attribution: Optional[dict[str, Any]]
    last_activity_at: Optional[datetime]
    lost_reason: Optional[str]
    lost_reason_other: Optional[str]
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    """Paged leads response.

    Two pagination modes coexist on the same endpoint:

      - **Offset mode** (default, legacy callers): caller passes
        ``page`` + ``size``; response carries ``total / page / size``.
      - **Cursor mode** (Step 6 FE): caller passes ``cursor`` + ``limit``;
        response carries ``next_cursor``. ``total`` is populated only
        when the caller opts in with ``with_total=true`` because the
        COUNT undoes the keyset performance win on large tables.
    """

    items: list[LeadOut]
    total: Optional[int] = None
    page: int = 1
    size: int = 50
    next_cursor: Optional[str] = None


# --- Reassign / bulk action request + response shapes -----------------------


class LeadReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadBulkReassign(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadBulkDelete(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class LeadBulkReassignResult(BaseModel):
    reassigned: int


class LeadBulkDeleteResult(BaseModel):
    deleted: int


# --- Scoring rule schemas ---------------------------------------------------


class LeadScoringRuleCreate(BaseModel):
    """Create a scoring rule.

    ``condition`` is a filter-DSL fragment (see
    ``src.app.core.leads.filter_dsl``). The service layer parses + runs
    ``validate_scorable`` to reject conditions that would reference
    contact-joined fields, which the in-memory engine can't evaluate.
    """

    name: str = Field(min_length=1, max_length=120)
    condition: dict[str, Any]
    points: int = Field(ge=-100, le=100)
    active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadScoringRuleUpdate(BaseModel):
    """Partial update. All fields optional; same validation as create
    applies whenever the field is supplied."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    condition: Optional[dict[str, Any]] = None
    points: Optional[int] = Field(default=None, ge=-100, le=100)
    active: Optional[bool] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadScoringRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    condition: dict[str, Any]
    points: int
    active: bool
    created_at: datetime
    updated_at: datetime


class LeadScoringRecomputeResult(BaseModel):
    """Returned by ``POST /leads/scoring-rules/recompute``. ``touched``
    is the number of leads whose ``lead_score`` changed."""

    touched: int
