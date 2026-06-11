"""HTTP routes for email-sequences.

  GET    /api/v1/email/sequences                     → paginated list
  POST   /api/v1/email/sequences                     → create
  GET    /api/v1/email/sequences/{id}                → read one + steps
  PATCH  /api/v1/email/sequences/{id}                → partial update
  DELETE /api/v1/email/sequences/{id}                → soft delete

  POST   /api/v1/email/sequences/{id}/enroll         → bulk enroll
  GET    /api/v1/email/sequences/enrollments         → list enrollments
  POST   /api/v1/email/sequences/enrollments/{id}/pause
  POST   /api/v1/email/sequences/enrollments/{id}/resume
  POST   /api/v1/email/sequences/enrollments/{id}/cancel

Sequence definition writes are gated by `email.sequences.manage`
(Owner / Admin / Sales Manager). Reads are gated by `email.read`.
Enroll + pause + resume + cancel are gated by `email.sequences.enroll`
(those three roles + Employee — reps enroll their own leads into
manager-built sequences).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email_sequences import service as sequences_service
from src.app.core.email_sequences.schemas import (
    EmailSequenceCreate,
    EmailSequenceListResponse,
    EmailSequenceRead,
    EmailSequenceStepRead,
    EmailSequenceUpdate,
    EnrollmentListResponse,
    EnrollmentRead,
    EnrollmentRequest,
    EnrollmentResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/email/sequences", tags=["Email Sequences"])


# --- Sequence CRUD --------------------------------------------------------


@router.get("", response_model=EmailSequenceListResponse)
async def list_sequences_endpoint(
    q: str | None = Query(default=None, max_length=255),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> EmailSequenceListResponse:
    """Paginated list of live sequences for the active tenant.
    Step rows are omitted from this list view — call GET /{id} for
    the full payload."""
    rows, total = await sequences_service.list_sequences(
        db, q=q, is_active=is_active, page=page, size=size
    )
    items: list[EmailSequenceRead] = []
    for r in rows:
        # `steps=[]` on the list view to keep the response small —
        # consumers that need steps call GET /{id}.
        items.append(EmailSequenceRead.model_validate(r))
    return EmailSequenceListResponse(
        items=items, total=total, page=page, size=size
    )


@router.post(
    "",
    response_model=EmailSequenceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_sequence_endpoint(
    payload: EmailSequenceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.manage")),
) -> EmailSequenceRead:
    """Create a sequence. Validates every step's template_id belongs
    to the active org and isn't soft-deleted; on failure the 400 lists
    the offending ids."""
    seq, steps = await sequences_service.create_sequence(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return _project_sequence(seq, steps)


@router.get("/{sequence_id}", response_model=EmailSequenceRead)
async def get_sequence_endpoint(
    sequence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> EmailSequenceRead:
    """Read one sequence + its ordered step list."""
    seq, steps = await sequences_service.get_sequence_with_steps(
        db, sequence_id=sequence_id
    )
    return _project_sequence(seq, steps)


@router.patch("/{sequence_id}", response_model=EmailSequenceRead)
async def update_sequence_endpoint(
    sequence_id: uuid.UUID,
    payload: EmailSequenceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.manage")),
) -> EmailSequenceRead:
    """Partial update. `steps` is full-replace when provided; 409
    when the sequence has active or paused enrollments."""
    seq, steps = await sequences_service.update_sequence(
        db,
        sequence_id=sequence_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return _project_sequence(seq, steps)


@router.delete("/{sequence_id}", response_model=EmailSequenceRead)
async def delete_sequence_endpoint(
    sequence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.manage")),
) -> EmailSequenceRead:
    """Soft-delete. Historical enrollments survive; the scheduler
    halts any active enrollments on the next tick (marks them
    completed via the sequence_inactive_or_deleted branch)."""
    seq = await sequences_service.delete_sequence(
        db,
        sequence_id=sequence_id,
        actor_id=user.legacy_uuid,
    )
    return _project_sequence(seq, [])


# --- Enrollment ------------------------------------------------------------


@router.post(
    "/{sequence_id}/enroll", response_model=EnrollmentResponse
)
async def enroll_endpoint(
    sequence_id: uuid.UUID,
    payload: EnrollmentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.enroll")),
) -> EnrollmentResponse:
    """Bulk-enroll up to 1000 contacts in one call. Dedupes against
    any non-terminal enrollment of the same (sequence, contact);
    skipped rows carry `skip_reason='already_enrolled'`."""
    results = await sequences_service.enroll(
        db,
        sequence_id=sequence_id,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        contact_ids=payload.contact_ids,
        lead_ids=payload.lead_ids,
    )
    enrolled = sum(1 for r in results if r.enrolled)
    return EnrollmentResponse(
        results=results,
        enrolled_count=enrolled,
        skipped_count=len(results) - enrolled,
    )


@router.get(
    "/enrollments", response_model=EnrollmentListResponse
)
async def list_enrollments_endpoint(
    sequence_id: uuid.UUID | None = Query(default=None),
    contact_id: uuid.UUID | None = Query(default=None),
    state: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> EnrollmentListResponse:
    """Paginated enrollment list for the dashboard."""
    rows, total = await sequences_service.list_enrollments(
        db,
        sequence_id=sequence_id,
        contact_id=contact_id,
        state=state,
        page=page,
        size=size,
    )
    return EnrollmentListResponse(
        items=[EnrollmentRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "/enrollments/{enrollment_id}/pause", response_model=EnrollmentRead
)
async def pause_enrollment_endpoint(
    enrollment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.enroll")),
) -> EnrollmentRead:
    """Operator pause. Marks pending step rows skipped so the
    scheduler ignores them. Resume re-inserts a fresh step row."""
    row = await sequences_service.pause_enrollment(
        db,
        enrollment_id=enrollment_id,
        actor_id=user.legacy_uuid,
    )
    return EnrollmentRead.model_validate(row)


@router.post(
    "/enrollments/{enrollment_id}/resume", response_model=EnrollmentRead
)
async def resume_enrollment_endpoint(
    enrollment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.enroll")),
) -> EnrollmentRead:
    """Resume a paused enrollment. Reschedules the current step at
    `now + delay_days`."""
    row = await sequences_service.resume_enrollment(
        db,
        enrollment_id=enrollment_id,
        actor_id=user.legacy_uuid,
    )
    return EnrollmentRead.model_validate(row)


@router.post(
    "/enrollments/{enrollment_id}/cancel", response_model=EnrollmentRead
)
async def cancel_enrollment_endpoint(
    enrollment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.sequences.enroll")),
) -> EnrollmentRead:
    """Terminal cancel — no resume."""
    row = await sequences_service.cancel_enrollment(
        db,
        enrollment_id=enrollment_id,
        actor_id=user.legacy_uuid,
    )
    return EnrollmentRead.model_validate(row)


# --- Helpers --------------------------------------------------------------


def _project_sequence(seq, steps) -> EmailSequenceRead:
    """Build the read projection — base sequence + ordered step list."""
    return EmailSequenceRead(
        id=seq.id,
        org_id=seq.org_id,
        name=seq.name,
        is_active=seq.is_active,
        created_by=seq.created_by,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[EmailSequenceStepRead.model_validate(s) for s in steps],
    )
