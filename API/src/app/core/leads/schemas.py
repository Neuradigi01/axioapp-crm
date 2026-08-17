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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.app.core.leads.models import LeadSource, LeadStatus
from src.app.core.tasks.models import TaskFollowupType
from src.app.shared.schemas import (
    BulkDelete,
    BulkDeleteResult,
    BulkIds,
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


# --- Update Status flow (leads-update-status-flow track) ---
#
# Bounds on ``NextFollowUpSpec.due_at``. Reject wildly out-of-band
# datetimes (year 1950, year 9999) so the leads-list sort by next
# follow-up and any downstream Celery scheduler that reads the value
# don't get poisoned by placeholder pickers or hostile input.
_FOLLOWUP_LOOKBACK_DAYS = 365
_FOLLOWUP_LOOKAHEAD_DAYS = 5 * 365


class FollowUpContactBasics(BaseModel):
    """Narrow contact patch surface exposed by the log-update endpoint.

    Only three fields — ``full_name``, ``phone``, ``email``. The wider
    ``contacts.update_service`` accepts ``assigned_to_id`` / ``tags`` /
    ``custom_data`` / ``source`` too; forwarding the whole payload
    would let a rep with ``leads.write`` mutate contact-owned fields
    a plain PATCH on ``/contacts`` would gate behind ``contacts.write``
    + additional permissions. Every unknown key is rejected.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    email: EmailStr | None = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NextFollowUpSpec(BaseModel):
    """One scheduled follow-up task to create alongside the log-update.

    Persists as a ``tbl_tasks`` row with ``followup_type`` set — the
    dashboard's Today's Follow-ups widget picks it up unchanged.
    """

    due_at: datetime
    followup_type: TaskFollowupType

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _bound_due_at(self) -> NextFollowUpSpec:
        from datetime import UTC, timedelta
        from datetime import datetime as _dt

        now = _dt.now(UTC)
        # Normalise: treat naive datetimes as UTC so the comparison never
        # raises on mixed-awareness inputs.
        due = self.due_at if self.due_at.tzinfo else self.due_at.replace(tzinfo=UTC)
        earliest = now - timedelta(days=_FOLLOWUP_LOOKBACK_DAYS)
        latest = now + timedelta(days=_FOLLOWUP_LOOKAHEAD_DAYS)
        if due < earliest or due > latest:
            raise ValueError(
                f"due_at must be within {_FOLLOWUP_LOOKBACK_DAYS} days in the past "
                f"and {_FOLLOWUP_LOOKAHEAD_DAYS} days in the future"
            )
        return self


class LogUpdateRequest(BaseModel):
    """Payload for ``POST /api/v1/leads/{id}/log-update``.

    ``if_current_stage`` is an optimistic-lock guard: the modal captures
    the lead's stage at open time and sends it here; if the DB has moved
    on since, the endpoint responds 409 so the rep re-opens with the
    fresh state instead of clobbering a colleague's move with fabricated
    ``status_change`` history.

    ``remarks`` is always written as a ``type='note'`` activity so it
    appears on the standard timeline without a new activity type.

    ``contact_basics`` / ``pipeline_stage`` / ``source`` / ``next_follow_up``
    are all optional — a bare ``{"if_current_stage":X, "remarks":"…"}``
    payload logs a note and does nothing else.
    """

    if_current_stage: str = Field(min_length=1, max_length=64)
    contact_basics: FollowUpContactBasics | None = None
    pipeline_stage: str | None = Field(default=None, min_length=1, max_length=64)
    source: LeadSource | None = None
    remarks: str = Field(min_length=1, max_length=2000)
    next_follow_up: NextFollowUpSpec | None = None
    # Owner change — when supplied AND different from the lead's
    # current owner, the service updates `assigned_to_id` inside the
    # same atomic transaction AND writes a `reassign` activity so the
    # timeline shows a proper "Reassigned Ravi → Priya" row.
    # ``null`` = clear owner (Unassigned). Omit the key = no change.
    # Reuses the existing `leads.reassign` permission (checked in the
    # router alongside `leads.write` when this field is present).
    assigned_to_id: uuid.UUID | None = None
    # Sentinel: the client sends `set_assigned_to=false` to mean "the
    # field is not being changed" — needed because Pydantic can't tell
    # `assigned_to_id: null` (intentional unassign) from "field omitted"
    # once the payload is deserialised. The FE sets it to `true` only
    # when the Owner control was actually touched.
    set_assigned_to: bool = False
    # Lost-reason pair — required (server side) when the target stage
    # is is_lost. Same picklist + shape as MoveStageRequest so the modal
    # can carry the reason atomically instead of firing a second call.
    lost_reason: str | None = Field(default=None, max_length=32)
    lost_reason_other: str | None = Field(default=None, max_length=255)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_lost_reason(self) -> LogUpdateRequest:
        _validate_lost_reason_pair(self.lost_reason, self.lost_reason_other)
        return self


class LeadOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    contact_id: uuid.UUID
    # W6 — non-null when the lead was created from a walk-in via
    # ``convert_walk_in_to_lead``. Powers the "Originated from walk-in"
    # chip + deep-link on the lead-detail page.
    source_walk_in_id: uuid.UUID | None = None
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


class LogUpdateResponse(BaseModel):
    """Response body for the log-update endpoint.

    ``next_follow_up_task_id`` is non-null iff the request supplied a
    ``next_follow_up`` block and the task was inserted. FE uses this
    to prepend the new task into the Follow-Up History panel without a
    refetch.
    """

    lead: LeadOut
    next_follow_up_task_id: uuid.UUID | None = None


class LeadIngestOut(LeadOut):
    """Response body for ``POST /leads`` and any other channel-agnostic
    create endpoint that funnels through ``leads.ingest.ingest()``.

    Extends :class:`LeadOut` with the discriminator the ingest layer
    already computes — ``"created"`` when a fresh row was inserted,
    ``"merged"`` when the picked contact already had an OPEN lead and
    the timeline got a "Touchpoint via <source>" activity instead. The
    UI reads this to show the right toast ("New lead created" vs
    "Existing lead updated") rather than sniffing a response header,
    which requires CORS ``Access-Control-Expose-Headers`` plumbing and
    breaks any client that goes through a proxy that strips it.

    The header stays too — for existing callers — but the body is the
    canonical channel going forward.
    """

    ingest_action: Literal["created", "merged"]


class LeadListResponse(BaseModel):
    """Paged leads response.

    Two pagination modes coexist on the same endpoint:

      - **Offset mode** (default, legacy callers): caller passes
        ``page`` + ``size``; response carries ``total / page / size``.
      - **Cursor mode** (Step 6 FE): caller passes ``cursor`` + ``limit``;
        response carries ``next_cursor``. ``total`` is populated only
        when the caller opts in with ``with_total=true`` because the
        COUNT undoes the keyset performance win on large tables.

    ``unfiltered_total`` is the tenant-wide count (no WHERE filters
    beyond the TenantScoped ORM predicate). Non-null only when the
    caller opts in with ``with_unfiltered_total=true``; the Leads
    Center header uses it to render ``(filtered/total)``.
    """

    items: list[LeadOut]
    total: int | None = None
    unfiltered_total: int | None = None
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


class LeadBulkMoveStageRequest(BulkIds, MoveStageRequest):
    """Bulk-move payload — the standard MoveStageRequest plus a capped
    ``ids`` list. Inheriting from `BulkIds` gets the min=1/max=200 cap
    the router-local class previously lacked (raw API caller could
    otherwise POST 10K ids)."""


class LeadBulkMoveStageResult(BaseModel):
    """Split result so the FE can show `"X moved, Y already there"`
    instead of undercounting silently."""

    moved: int
    already_in_stage: int = 0


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


class PipelineValueByCurrency(BaseModel):
    """Per-currency open / won bucket. Rendered alongside the flat
    header totals so mixed-currency orgs can see the split instead of
    a nonsense sum. Empty list means every lead uses the org default
    (the flat `open_value`/`won_value_this_month` are already correct
    in that case)."""

    currency: str
    open_value: Decimal
    won_value_this_month: Decimal


class PipelineValueRollup(BaseModel):
    """Summary numbers rendered in the header strip above the kanban /
    list view.

    Scope follows the caller's row-level visibility — reps without
    ``users.read`` see only their own leads' contribution, managers
    see the full org roll-up.

    ``currency`` is the org's default ISO-4217 code. The flat
    ``open_value`` + ``won_value_this_month`` sums treat leads with a
    NULL per-row `currency` as org-default; leads with a non-null
    override are NOT folded into the flat total (would produce a
    misleading mixed-currency sum). Instead they show up in
    ``by_currency`` alongside the default-bucket totals so the FE can
    render an accurate breakdown.
    """

    open_value: Decimal
    won_value_this_month: Decimal
    open_count: int
    won_count_this_month: int
    lost_count_this_month: int
    currency: str
    # Per-currency split. Includes the org default bucket AND every
    # non-default per-row currency the current filter matched. Empty
    # when every lead uses the org default currency (flat totals are
    # authoritative in that case).
    by_currency: list[PipelineValueByCurrency] = Field(default_factory=list)
