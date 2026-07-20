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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.core.leads.models import LeadSource, LeadStatus
from src.app.shared.schemas import (
    BulkDelete,
    BulkDeleteResult,
    BulkReassign,
    BulkReassignResult,
    TimestampedOrgScopedOut,
)

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


def _validate_lost_reason_pair(lost_reason: str | None, lost_reason_other: str | None) -> None:
    """Shared validator: `lost_reason` must be in the picklist; when
    `lost_reason == 'other'`, the free-text `lost_reason_other` must
    be non-empty."""
    if lost_reason is not None and lost_reason not in LOST_REASONS:
        raise ValueError(f"lost_reason must be one of {LOST_REASONS}; got {lost_reason!r}")
    if lost_reason == "other" and not (lost_reason_other and lost_reason_other.strip()):
        raise ValueError("lost_reason_other is required when lost_reason='other'")


class LeadCreate(BaseModel):
    contact_id: uuid.UUID
    pipeline_stage: str | None = Field(default=None, max_length=64)
    assigned_to_id: uuid.UUID | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    # ISO-4217 3-letter code. Omitted → renderers fall back to the
    # org's default currency (from ``/users/me → org.currency``).
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_close_date: date | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)
    source: LeadSource = LeadSource.manual
    # Channel-supplied provenance (widget UTM, ad webhook ids, etc.).
    # Stays None for manual + bulk-import paths.
    attribution: dict[str, Any] | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadUpdate(BaseModel):
    """Partial update. `pipeline_stage` and `status` are NOT here on
    purpose — stage changes go through the move-stage endpoint so the
    pipeline engine logs activity + audit and keeps status in sync.

    `lost_reason` + `lost_reason_other` ARE accepted so a follow-up
    edit can refine the reason after the initial Lost transition; the
    validators run regardless of how the row arrived at `lost`.
    """

    contact_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_close_date: date | None = None
    custom_data: dict[str, Any] | None = None
    lost_reason: str | None = Field(default=None, max_length=32)
    lost_reason_other: str | None = Field(default=None, max_length=255)
    # Won-capture fields (F2). Populated by the move-stage endpoint on
    # move-to-Won, but also editable via PATCH so a rep can refine
    # ``won_value`` / ``close_date`` / ``won_reason`` after the initial
    # transition. Symmetric to the lost_reason pair above.
    won_value: Decimal | None = Field(default=None, ge=0)
    close_date: date | None = None
    won_reason: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_lost_reason(self) -> LeadUpdate:
        _validate_lost_reason_pair(self.lost_reason, self.lost_reason_other)
        return self


class MoveStageRequest(BaseModel):
    """Move-stage request.

    On move-to-Lost: ``lost_reason`` (picklist) is required. On
    move-to-Won: ``won_value`` / ``close_date`` / ``won_reason`` are
    all optional at the API layer — the FE prompts and enforces
    per-org preference. Leaving them empty is intentional API-compat
    (existing automations / tests calling move-stage on Won won't
    422). Rep can also fill them later via PATCH /leads/{id}.
    """

    to_stage: str = Field(min_length=1, max_length=64)
    lost_reason: str | None = Field(default=None, max_length=32)
    lost_reason_other: str | None = Field(default=None, max_length=255)
    won_value: Decimal | None = Field(default=None, ge=0)
    close_date: date | None = None
    won_reason: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_lost_reason(self) -> MoveStageRequest:
        _validate_lost_reason_pair(self.lost_reason, self.lost_reason_other)
        return self


class LeadOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    contact_id: uuid.UUID
    pipeline_stage: str
    status: LeadStatus
    source: LeadSource
    assigned_to_id: uuid.UUID | None
    budget: Decimal | None
    # ISO-4217 3-letter code (nullable — omit → org default at render).
    currency: str | None = None
    expected_close_date: date | None
    # Rule-engine output, ``[0, 100]``. Computed by
    # ``src.app.core.leads.scoring`` after every create / update that
    # touches a rule-relevant column. The hourly Celery sweep keeps the
    # value fresh when rules themselves change.
    lead_score: int = 0
    custom_data: dict[str, Any]
    attribution: dict[str, Any] | None
    last_activity_at: datetime | None
    lost_reason: str | None
    lost_reason_other: str | None
    # Won-capture fields (F2). Set by the move-stage endpoint when the
    # destination stage is is_won.
    won_value: Decimal | None = None
    close_date: date | None = None
    won_reason: str | None = None
    # Lifecycle timestamps (F22). Auto-set by the move-stage service on
    # first entry into an is_won / is_lost stage.
    won_at: datetime | None = None
    lost_at: datetime | None = None


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
    total: int | None = None
    page: int = 1
    size: int = 50
    next_cursor: str | None = None


# --- Reassign / bulk action request + response shapes -----------------------


class LeadReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


LeadBulkReassign = BulkReassign
LeadBulkDelete = BulkDelete

LeadBulkReassignResult = BulkReassignResult
LeadBulkDeleteResult = BulkDeleteResult


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

    name: str | None = Field(default=None, min_length=1, max_length=120)
    condition: dict[str, Any] | None = None
    points: int | None = Field(default=None, ge=-100, le=100)
    active: bool | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class LeadScoringRuleOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    name: str
    condition: dict[str, Any]
    points: int
    active: bool


class LeadScoringRecomputeResult(BaseModel):
    """Returned by ``POST /leads/scoring-rules/recompute``. ``touched``
    is the number of leads whose ``lead_score`` changed."""

    touched: int


# --- Pipeline value roll-up (F23) ------------------------------------------


class PipelineValueRollup(BaseModel):
    """Summary numbers rendered in the header strip above the kanban /
    list view.

    Scope follows the caller's row-level visibility — reps without
    ``users.read`` see only their own leads' contribution, managers
    see the full org roll-up.

    ``currency`` is the org's default ISO-4217 code; per-lead
    ``currency`` overrides are ignored in this v1 roll-up (mixed-
    currency orgs will need a future weighted conversion; not a
    common case yet).
    """

    open_value: Decimal
    won_value_this_month: Decimal
    open_count: int
    won_count_this_month: int
    lost_count_this_month: int
    currency: str
