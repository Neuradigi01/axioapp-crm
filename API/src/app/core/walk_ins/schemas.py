"""Pydantic v2 schemas for the walk-ins module.

`QuickRegisterPayload` is the reception-desk one-shot: phone is the
required key the service uses to look up an existing contact (and
create one if missing). `QuickRegisterResponse` returns both the
walk-in row and the resolved contact so the caller can show the
contact's existing tags / history alongside the new walk-in.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.app.core.contacts.schemas import ContactOut
from src.app.core.walk_ins.models import WalkInStatus
from src.app.shared.schemas import TimestampedOrgScopedOut


class WalkInCreate(BaseModel):
    contact_id: uuid.UUID
    requirement: str | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    assigned_to_id: uuid.UUID | None = None
    notes: str | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)
    # W8/W9/W11 — extended reception-desk fields. All optional; orgs
    # that don't track queue time / group size / return date leave
    # them NULL and the current UX is unchanged.
    party_size: int | None = Field(default=None, ge=1, le=99)
    wait_started_at: datetime | None = None
    expected_return_date: date | None = None


class WalkInUpdate(BaseModel):
    """Partial update. `time_in` / `time_out` are server-managed (via
    `quick_register` and `checkout` respectively), so they're not in
    this schema — the timing fields don't get rewritten through a
    generic PATCH."""

    requirement: str | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    assigned_to_id: uuid.UUID | None = None
    status: WalkInStatus | None = None
    notes: str | None = None
    custom_data: dict[str, Any] | None = None
    # W8/W9/W11 — editable after registration (rep can add / correct).
    party_size: int | None = Field(default=None, ge=1, le=99)
    wait_started_at: datetime | None = None
    expected_return_date: date | None = None


class QuickRegisterPayload(BaseModel):
    """Reception-desk one-shot. `phone` is required so the service has
    a deduplication key; everything else is optional."""

    phone: str = Field(min_length=1, max_length=32)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    source: str | None = Field(default=None, max_length=64)
    requirement: str | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    assigned_to_id: uuid.UUID | None = None
    notes: str | None = None
    custom_data: dict[str, Any] = Field(default_factory=dict)
    # W8/W9/W11 — reception can capture these at registration too.
    party_size: int | None = Field(default=None, ge=1, le=99)
    wait_started_at: datetime | None = None
    expected_return_date: date | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class WalkInOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    contact_id: uuid.UUID
    time_in: datetime
    time_out: datetime | None
    duration_min: Decimal | None
    requirement: str | None
    budget: Decimal | None
    assigned_to_id: uuid.UUID | None
    status: WalkInStatus
    notes: str | None
    custom_data: dict[str, Any]
    last_activity_at: datetime | None
    linked_lead_id: uuid.UUID | None
    # W8/W9/W11 — extended reception-desk fields (migration 0161).
    party_size: int | None = None
    wait_started_at: datetime | None = None
    expected_return_date: date | None = None


class QuickRegisterResponse(BaseModel):
    """Return both the walk-in and its resolved contact so the
    reception-desk UI can show prior tags / source on first paint."""

    walk_in: WalkInOut
    contact: ContactOut
    contact_was_created: bool


# --- Reassign / bulk-action / convert shapes -------------------------------


class WalkInReassign(BaseModel):
    """Single-row reassign request. `null` clears the owner."""

    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class WalkInBulkReassign(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class WalkInBulkCheckout(BaseModel):
    """Bulk-checkout (stamp `time_out=now()`) — the walk-in equivalent
    of "mark done". Per-row processing because already-checked-out
    walk-ins are skipped, not errored."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class WalkInBulkReassignResult(BaseModel):
    """`reassigned` counts rows whose owner actually changed this call.
    `already_assigned` counts rows skipped because they already owned
    the target — surfaced so the FE can show an honest "X reassigned,
    Y already had this owner" summary instead of undercounting."""

    reassigned: int
    already_assigned: int = 0


class WalkInBulkCheckoutResult(BaseModel):
    """`checked_out` counts rows actually stamped this call.
    `already_checked_out` counts rows skipped because they had a
    `time_out` already — same semantic as the single-row endpoint."""

    checked_out: int
    already_checked_out: int


class WalkInConvertRequest(BaseModel):
    """Convert a walk-in to a Lead.

    `contact_link_mode`:
      - `"auto"` (default) — keep the walk-in's existing contact_id.
        The walk-in already has a contact via quick-register, so
        re-using it is the right default.
      - `"link"` — use a different `linked_contact_id` (e.g. the rep
        realised mid-visit the walk-in belongs to an existing customer).
        Tenant-scoped validation rejects cross-org targets with 422.

    `source` and `notes` are stamped on the new Lead. `source`
    defaults to `"walk_in"` at the service layer.
    """

    contact_link_mode: Literal["auto", "link"] = "auto"
    linked_contact_id: uuid.UUID | None = None
    notes: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class WalkInConvertResponse(BaseModel):
    walk_in_id: uuid.UUID
    contact_id: uuid.UUID
    lead_id: uuid.UUID


# --- Bulk delete + KPI rollup (W1 / W7) -----------------------------------


class WalkInBulkDelete(BaseModel):
    """Bulk-delete N walk-ins in one call. Mirror of the leads bulk-
    delete pattern: single SQL DELETE ... WHERE id IN (...) with
    org-scope, single audit entry."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class WalkInBulkDeleteResult(BaseModel):
    deleted: int


class WalkInsRollup(BaseModel):
    """Server-side KPI roll-up for the walk-ins page header (W7).

    Scope follows caller row visibility (org vs. personal) — decided
    server-side. Numbers are computed via one grouped SQL query
    against the full org's data, not client-side over the loaded
    page, so multi-location busy showrooms show accurate totals.

    ``avg_duration_min`` is null when no completed visits exist in
    the last 30 days (rather than showing 0, which would misrepresent
    "quick visits"). ``conversion_rate_pct`` is null when no visits
    have been checked out or converted yet in the last 30 days."""

    today_count: int
    today_converted: int
    open_now: int
    interested_or_follow_up: int
    conversion_rate_pct: float | None
    avg_duration_min: float | None
    avg_wait_min: float | None
