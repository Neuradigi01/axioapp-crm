"""Pydantic v2 schemas for the email-sequences API.

Two halves:

  * **Sequence definitions** — `EmailSequenceCreate` / `Update` /
    `Read` plus the nested `StepCreate` / `StepRead`. A sequence's
    step list is materialised on create and replaceable on update
    (full-replace semantics keeps the order contract simple).

  * **Enrollments** — `EnrollmentRequest` (bulk), `EnrollmentResult`
    (per-id success/skip), `EnrollmentRead` (single row projection).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel

# --- Steps ----------------------------------------------------------------


class EmailSequenceStepCreate(BaseModel):
    """One row inside the `steps` array of a create/update payload.

    `step_order` is server-assigned (1-based, dense) when writing — the
    payload's order is the authoritative ordering. `delay_days` is
    relative to the previous step's send (or to enrollment for step 1).
    """

    delay_days: int = Field(ge=0, le=365)
    template_id: uuid.UUID

    model_config = ConfigDict(extra="forbid")


class EmailSequenceStepRead(ORMModel):
    """Step projection on read."""

    id: uuid.UUID
    sequence_id: uuid.UUID
    step_order: int
    delay_days: int
    template_id: uuid.UUID


# --- Sequence ------------------------------------------------------------


class EmailSequenceCreate(BaseModel):
    """`POST /api/v1/email/sequences` body.

    At least one step required — a sequence without steps is a no-op.
    Steps are saved in the order they appear in the array (`step_order
    = index + 1`).
    """

    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True
    steps: list[EmailSequenceStepCreate] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(str_strip_whitespace=True)


class EmailSequenceUpdate(BaseModel):
    """Partial update for `PATCH /api/v1/email/sequences/{id}`.

    `steps` is **full-replace** when provided: passing it rewrites the
    sequence's step list entirely. Omit to keep existing steps.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    steps: list[EmailSequenceStepCreate] | None = Field(default=None, min_length=1, max_length=50)

    model_config = ConfigDict(str_strip_whitespace=True)


class EmailSequenceRead(ORMModel):
    """Sequence projection on read — includes the materialised step list
    so the editor round-trips in a single fetch."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    steps: list[EmailSequenceStepRead] = Field(default_factory=list)


class EmailSequenceListResponse(BaseModel):
    items: list[EmailSequenceRead]
    total: int
    page: int
    size: int


# --- Enrollment -----------------------------------------------------------


class EnrollmentRequest(BaseModel):
    """`POST /api/v1/email/sequences/{id}/enroll` body.

    Bulk enrol. `lead_ids` is optional context — when supplied with
    `contact_ids` of the same length, the i-th lead is associated with
    the i-th contact's enrollment. Mismatched length → 400 in the
    router.
    """

    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    lead_ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class EnrollmentResultRow(BaseModel):
    """One row of the enroll response — per-contact outcome.

    `enrollment_id` is populated on success; `skip_reason` is populated
    on skip. Never both.
    """

    contact_id: uuid.UUID
    enrollment_id: uuid.UUID | None = None
    enrolled: bool
    skip_reason: str | None = None


class EnrollmentResponse(BaseModel):
    """`POST /api/v1/email/sequences/{id}/enroll` response shape."""

    results: list[EnrollmentResultRow]
    enrolled_count: int
    skipped_count: int


class EnrollmentRead(ORMModel):
    """Enrollment projection on read — for the dashboard list view."""

    id: uuid.UUID
    org_id: uuid.UUID
    sequence_id: uuid.UUID
    contact_id: uuid.UUID
    lead_id: uuid.UUID | None
    enrolled_by: uuid.UUID
    enrolled_at: datetime
    state: str
    state_changed_at: datetime
    current_step_order: int


class EnrollmentListResponse(BaseModel):
    items: list[EnrollmentRead]
    total: int
    page: int
    size: int


__all__ = [
    "EmailSequenceCreate",
    "EmailSequenceListResponse",
    "EmailSequenceRead",
    "EmailSequenceStepCreate",
    "EmailSequenceStepRead",
    "EmailSequenceUpdate",
    "EnrollmentListResponse",
    "EnrollmentRead",
    "EnrollmentRequest",
    "EnrollmentResponse",
    "EnrollmentResultRow",
]
