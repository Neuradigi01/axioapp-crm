"""Service layer for `email_sequences`.

Five concerns:

  1. **Sequence CRUD** — create / list / get / update / soft-delete.
     `steps` is materialised on create + full-replaced on update so
     the order contract stays simple (no positional patching surface).
  2. **Template-cross-org validation** — every `template_id` in the
     steps array must belong to the active org AND not be soft-deleted.
     Cross-org id → 400. Soft-deleted template id → 400.
  3. **Bulk enroll** — per-contact dedupe against existing non-terminal
     enrollments; returns per-id success/skip rows so the UI can
     surface "X enrolled, Y skipped".
  4. **Pause / resume / cancel** — explicit state transitions. Pause
     additionally marks any pending enrollment-step rows as skipped
     with reason so the scheduler ignores them; resume reinstates the
     current step at `now + delay_days`.
  5. **List enrollments** — paginated + filterable for the
     dashboard. RLS handles tenant isolation.

Audit events fire on create / update / delete / enroll / state change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.email_sequences import data_access as email_seq_da
from src.app.core.email_sequences.models import (
    EmailSequence,
    EmailSequenceEnrollment,
    EmailSequenceEnrollmentStep,
    EmailSequenceStep,
    EnrollmentState,
)
from src.app.core.email_sequences.schemas import (
    EmailSequenceCreate,
    EmailSequenceStepCreate,
    EmailSequenceUpdate,
    EnrollmentResultRow,
)

# --- Step 20: workflow-engine shim --------------------------------------


async def _try_enroll_via_workflow(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sequence_name: str,
    contact_ids: list[uuid.UUID],
) -> list[EnrollmentResultRow] | None:
    """If a workflow row exists for this sequence (created by the
    Step-20 data migration), enroll each contact via
    :func:`core.workflows.engine.start_run` + return the per-contact
    result rows. Otherwise return ``None`` so the legacy code path
    runs (transitional safety net).

    The migration writes one workflow per sequence with the canonical
    name ``f"Sequence: {seq.name}"``. The lookup is org-scoped so
    same-named sequences across tenants never bleed.
    """
    from sqlalchemy import select

    from src.app.core.workflows import engine as workflows_engine
    from src.app.core.workflows.models import Workflow

    canonical = f"Sequence: {sequence_name}"
    stmt = select(Workflow).where(
        Workflow.org_id == org_id, Workflow.name == canonical
    )
    workflow = (await session.execute(stmt)).scalar_one_or_none()
    if workflow is None:
        return None

    results: list[EnrollmentResultRow] = []
    for contact_id in contact_ids:
        try:
            run = await workflows_engine.start_run(
                session,
                workflow=workflow,
                contact_id=contact_id,
                trigger_event_id=None,
                trigger_payload={"contact_id": str(contact_id), "sequence_shim": True},
            )
            results.append(
                EnrollmentResultRow(
                    contact_id=contact_id,
                    enrollment_id=run.id if run else None,
                    enrolled=bool(run),
                    skip_reason=None if run else "workflow_refused",
                )
            )
        except Exception as exc:  # pragma: no cover — defensive
            results.append(
                EnrollmentResultRow(
                    contact_id=contact_id,
                    enrollment_id=None,
                    enrolled=False,
                    skip_reason=f"workflow_error: {type(exc).__name__}",
                )
            )
    return results


# --- Helpers --------------------------------------------------------------


async def _validate_template_ids(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_ids: list[uuid.UUID],
) -> None:
    """Reject if any template id doesn't point at a live email
    template in the active org.

    Post-Step-10 of ``tasks/template-library``: queries the central
    ``tbl_message_templates`` table via the email-sequences DAL.
    Tenant RLS would already cull cross-org ids, but the explicit
    count check surfaces a clear 400 rather than an opaque "step
    missing" at fire time.
    """
    if not template_ids:
        return
    found = await email_seq_da.list_valid_email_template_ids(session, list(template_ids))
    missing = sorted(set(template_ids) - found)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown or archived template ids: {missing}. "
                "Every step.template_id must point to a published "
                "email template in this workspace."
            ),
        )


async def _load_steps(session: AsyncSession, *, sequence_id: uuid.UUID) -> list[EmailSequenceStep]:
    """Steps in `step_order` ASC — used by `EmailSequenceRead` and
    by the scheduler when advancing to the next step."""
    return await email_seq_da.list_steps_in_order(session, sequence_id=sequence_id)


# --- Sequence CRUD --------------------------------------------------------


async def list_sequences(
    session: AsyncSession,
    *,
    q: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[EmailSequence], int]:
    """Paginated list, soft-deleted rows excluded."""
    total = await email_seq_da.count_sequences_filtered(session, q=q, is_active=is_active)
    rows = await email_seq_da.list_sequences_page(
        session,
        q=q,
        is_active=is_active,
        offset=(page - 1) * size,
        limit=size,
    )
    return rows, total


async def get_sequence(session: AsyncSession, *, sequence_id: uuid.UUID) -> EmailSequence:
    """Load a single sequence. 404 when missing or soft-deleted."""
    row = await email_seq_da.get_sequence_by_id(session, sequence_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email sequence {sequence_id} not found.",
        )
    return row


async def get_sequence_with_steps(
    session: AsyncSession, *, sequence_id: uuid.UUID
) -> tuple[EmailSequence, list[EmailSequenceStep]]:
    """Sequence + its steps in display order — for the read endpoint."""
    seq = await get_sequence(session, sequence_id=sequence_id)
    steps = await _load_steps(session, sequence_id=sequence_id)
    return seq, steps


async def create_sequence(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: EmailSequenceCreate,
) -> tuple[EmailSequence, list[EmailSequenceStep]]:
    """Validate template ids, persist sequence + steps in one txn.

    Audit-emits `email.sequence.created` with the step count.
    """
    template_ids = [s.template_id for s in payload.steps]
    await _validate_template_ids(session, org_id=org_id, template_ids=template_ids)

    seq = email_seq_da.add_sequence(
        session,
        EmailSequence(
            org_id=org_id,
            name=payload.name,
            is_active=payload.is_active,
            created_by=actor_id,
        ),
    )
    try:
        await session.flush()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"A sequence named {payload.name!r} already exists in this workspace."),
        ) from None

    steps = _materialise_steps(org_id=org_id, sequence_id=seq.id, payload_steps=payload.steps)
    email_seq_da.add_sequence_steps(session, steps)
    await session.commit()
    await session.refresh(seq)
    for s in steps:
        await session.refresh(s)

    await audit.log(
        "email.sequence.created",
        entity_type="email_sequence",
        entity_id=seq.id,
        after={"name": seq.name, "step_count": len(steps)},
        user_id=actor_id,
    )
    return seq, steps


def _materialise_steps(
    *,
    org_id: uuid.UUID,
    sequence_id: uuid.UUID,
    payload_steps: list[EmailSequenceStepCreate],
) -> list[EmailSequenceStep]:
    """Translate the payload's ordered list into ORM rows with dense
    1-based `step_order` values."""
    return [
        EmailSequenceStep(
            org_id=org_id,
            sequence_id=sequence_id,
            step_order=idx + 1,
            delay_days=payload_step.delay_days,
            template_id=payload_step.template_id,
        )
        for idx, payload_step in enumerate(payload_steps)
    ]


async def update_sequence(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: EmailSequenceUpdate,
) -> tuple[EmailSequence, list[EmailSequenceStep]]:
    """Partial update. `steps` is full-replace when provided.

    Audit-emits `email.sequence.updated` with the changed-fields keys.
    """
    seq = await get_sequence(session, sequence_id=sequence_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        steps = await _load_steps(session, sequence_id=seq.id)
        return seq, steps

    if "name" in changes:
        seq.name = changes["name"]
    if "is_active" in changes:
        seq.is_active = changes["is_active"]

    new_steps: list[EmailSequenceStep] | None = None
    if payload.steps is not None:
        await _validate_template_ids(
            session,
            org_id=seq.org_id,
            template_ids=[s.template_id for s in payload.steps],
        )
        # Full-replace: drop existing step rows then re-insert. Steps are
        # referenced by `email_sequence_enrollment_steps.step_id` but
        # CASCADE there isn't desirable — we keep the historical step
        # rows for in-flight enrollments by NOT deleting steps an
        # enrollment_step still references. Practical safety: refuse
        # update when any active enrollment exists.
        active_enrollments = await email_seq_da.count_non_terminal_enrollments(session, seq.id)
        if active_enrollments > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot replace steps while the sequence has "
                    "active or paused enrollments. Cancel or complete "
                    "those enrollments first, or create a new sequence."
                ),
            )
        await email_seq_da.delete_steps_for_sequence(session, seq.id)
        new_steps = _materialise_steps(
            org_id=seq.org_id,
            sequence_id=seq.id,
            payload_steps=payload.steps,
        )
        email_seq_da.add_sequence_steps(session, new_steps)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"A sequence named {seq.name!r} already exists in this workspace."),
        ) from None
    await session.refresh(seq)
    if new_steps is not None:
        for s in new_steps:
            await session.refresh(s)
        steps = new_steps
    else:
        steps = await _load_steps(session, sequence_id=seq.id)

    await audit.log(
        "email.sequence.updated",
        entity_type="email_sequence",
        entity_id=seq.id,
        after={"changed": sorted(changes.keys())},
        user_id=actor_id,
    )
    return seq, steps


async def delete_sequence(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> EmailSequence:
    """Soft-delete. Historical enrollments keep their FK; the
    scheduler's enrollment loop filters out soft-deleted sequences so
    no further sends happen."""
    seq = await get_sequence(session, sequence_id=sequence_id)
    seq.deleted_at = datetime.now(UTC)
    seq.is_active = False
    await session.commit()
    await session.refresh(seq)
    await audit.log(
        "email.sequence.deleted",
        entity_type="email_sequence",
        entity_id=seq.id,
        after={"name": seq.name},
        user_id=actor_id,
    )
    return seq


# --- Enrollment -----------------------------------------------------------


async def enroll(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
    lead_ids: list[uuid.UUID] | None = None,
) -> list[EnrollmentResultRow]:
    """Bulk-enroll contacts.

    Step 20 — sequence runtime is absorbed into workflows. This
    function now shims through :func:`core.workflows.engine.start_run`
    against the workflow row produced for the sequence by the
    Step-20 data migration (``0145_migrate_sequences_to_workflows``).

    The same per-contact dedupe + result-row shape are preserved so
    public callers (the legacy ``POST /email/sequences/{id}/enroll``
    endpoint) see no contract change. Sequences that haven't been
    migrated yet (edge case during transition) fall back to the
    original code path so in-flight ops keep working.

    Audit-emits ``email.sequence.enrolled`` per success.
    """
    # --- Step 20 shim: route through workflows when a migrated
    # workflow row is available. The data migration installs each
    # sequence as a workflow named ``f"Sequence: {seq.name}"`` so
    # the lookup is name-based.
    seq = await get_sequence(session, sequence_id=sequence_id)
    workflow_results = await _try_enroll_via_workflow(
        session,
        org_id=org_id,
        sequence_name=seq.name,
        contact_ids=contact_ids,
    )
    if workflow_results is not None:
        return workflow_results

    # Legacy code path — only reached when the sequence hasn't been
    # migrated to a workflow yet (e.g. created after the migration ran
    # but before the shim caught up). Beat scheduler is a no-op, so
    # these enrollments will sit dormant; a follow-up migration will
    # sweep + convert.
    steps = await _load_steps(session, sequence_id=seq.id)
    if not steps:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Cannot enroll — sequence has no steps. Edit the sequence to add steps first."),
        )
    if not seq.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot enroll — sequence is inactive. Reactivate it from the sequences page first."
            ),
        )
    if lead_ids is not None and len(lead_ids) != len(contact_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "lead_ids and contact_ids must be the same length "
                "(one lead per contact). Pass null to skip lead tagging."
            ),
        )

    # Dedupe: any non-terminal enrollment of (sequence, contact_id)
    # blocks a re-enroll. Completed / cancelled enrollments do NOT
    # block — operators can re-run a finished sequence.
    blocked = await email_seq_da.list_active_enrollment_ids_for_contacts(
        session, sequence_id=seq.id, contact_ids=contact_ids
    )

    step1 = steps[0]
    now = datetime.now(UTC)
    results: list[EnrollmentResultRow] = []
    new_enrollment_rows: list[
        tuple[EmailSequenceEnrollment, EmailSequenceEnrollmentStep, uuid.UUID]
    ] = []

    for idx, contact_id in enumerate(contact_ids):
        if contact_id in blocked:
            results.append(
                EnrollmentResultRow(
                    contact_id=contact_id,
                    enrollment_id=blocked[contact_id],
                    enrolled=False,
                    skip_reason="already_enrolled",
                )
            )
            continue

        lead_id = lead_ids[idx] if lead_ids is not None and idx < len(lead_ids) else None
        enrollment = email_seq_da.add_enrollment(
            session,
            EmailSequenceEnrollment(
                org_id=org_id,
                sequence_id=seq.id,
                contact_id=contact_id,
                lead_id=lead_id,
                enrolled_by=actor_id,
                enrolled_at=now,
                state=EnrollmentState.active.value,
                state_changed_at=now,
                current_step_order=1,
            ),
        )
        await session.flush()

        # Step 1 is scheduled at now() so the next beat tick fires it
        # (60s latency floor per spec).
        es = email_seq_da.add_enrollment_step(
            session,
            EmailSequenceEnrollmentStep(
                org_id=org_id,
                enrollment_id=enrollment.id,
                step_id=step1.id,
                scheduled_at=now,
            ),
        )
        new_enrollment_rows.append((enrollment, es, contact_id))

    await session.commit()
    for enrollment, _es, contact_id in new_enrollment_rows:
        await session.refresh(enrollment)
        results.append(
            EnrollmentResultRow(
                contact_id=contact_id,
                enrollment_id=enrollment.id,
                enrolled=True,
                skip_reason=None,
            )
        )
        await audit.log(
            "email.sequence.enrolled",
            entity_type="email_sequence_enrollment",
            entity_id=enrollment.id,
            after={
                "sequence_id": str(seq.id),
                "contact_id": str(contact_id),
            },
            user_id=actor_id,
        )
    # Order results by input contact order for UI determinism.
    by_contact = {r.contact_id: r for r in results}
    ordered = [by_contact[c] for c in contact_ids if c in by_contact]
    return ordered


async def get_enrollment(
    session: AsyncSession, *, enrollment_id: uuid.UUID
) -> EmailSequenceEnrollment:
    row = await email_seq_da.get_enrollment_by_id(session, enrollment_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrollment {enrollment_id} not found.",
        )
    return row


async def list_enrollments(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    state: str | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[EmailSequenceEnrollment], int]:
    total = await email_seq_da.count_enrollments_filtered(
        session,
        sequence_id=sequence_id,
        contact_id=contact_id,
        state=state,
    )
    rows = await email_seq_da.list_enrollments_page(
        session,
        sequence_id=sequence_id,
        contact_id=contact_id,
        state=state,
        offset=(page - 1) * size,
        limit=size,
    )
    return rows, total


async def pause_enrollment(
    session: AsyncSession,
    *,
    enrollment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> EmailSequenceEnrollment:
    """Operator pause. Marks pending enrollment-step rows as skipped
    so the scheduler ignores them; the enrollment can be resumed later.

    Idempotent — pausing an already-paused enrollment is a no-op.
    """
    enrollment = await get_enrollment(session, enrollment_id=enrollment_id)
    if enrollment.is_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Cannot pause an enrollment in terminal state ({enrollment.state})."),
        )
    if enrollment.state == EnrollmentState.paused_manual.value:
        return enrollment

    now = datetime.now(UTC)
    enrollment.state = EnrollmentState.paused_manual.value
    enrollment.state_changed_at = now

    # Skip any pending step rows so the scheduler won't pick them up
    # while the enrollment is paused. Resume re-inserts a fresh step
    # row at the appropriate time.
    await email_seq_da.skip_pending_enrollment_steps(
        session,
        enrollment_id=enrollment.id,
        skip_reason="enrollment_paused",
    )
    await session.commit()
    await session.refresh(enrollment)
    await audit.log(
        "email.sequence.enrollment_paused",
        entity_type="email_sequence_enrollment",
        entity_id=enrollment.id,
        after={"state": enrollment.state},
        user_id=actor_id,
    )
    return enrollment


async def resume_enrollment(
    session: AsyncSession,
    *,
    enrollment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> EmailSequenceEnrollment:
    """Resume a paused enrollment. Flips state back to `active` and
    schedules the current step at `now + delay_days` (relative to
    `now` — the delay clock restarts so a paused sequence doesn't
    fire immediately on resume of long pauses).

    Resume of `paused_on_reply` is allowed; the operator may
    consciously want to re-engage after a reply.

    Idempotent — resuming an already-active enrollment is a no-op.
    """
    enrollment = await get_enrollment(session, enrollment_id=enrollment_id)
    if enrollment.state == EnrollmentState.active.value:
        return enrollment
    if enrollment.is_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Cannot resume an enrollment in terminal state ({enrollment.state})."),
        )

    steps = await _load_steps(session, sequence_id=enrollment.sequence_id)
    by_order = {s.step_order: s for s in steps}
    current = by_order.get(enrollment.current_step_order)
    if current is None:
        # Current step deleted (sequence rewritten under us) — there's
        # nothing safe to resume into, so close the enrollment.
        enrollment.state = EnrollmentState.completed.value
        enrollment.state_changed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(enrollment)
        return enrollment

    now = datetime.now(UTC)
    enrollment.state = EnrollmentState.active.value
    enrollment.state_changed_at = now

    # Insert a fresh pending step row scheduled at now + delay_days.
    email_seq_da.add_enrollment_step(
        session,
        EmailSequenceEnrollmentStep(
            org_id=enrollment.org_id,
            enrollment_id=enrollment.id,
            step_id=current.id,
            scheduled_at=now + timedelta(days=current.delay_days),
        ),
    )
    await session.commit()
    await session.refresh(enrollment)
    await audit.log(
        "email.sequence.enrollment_resumed",
        entity_type="email_sequence_enrollment",
        entity_id=enrollment.id,
        after={"state": enrollment.state},
        user_id=actor_id,
    )
    return enrollment


async def cancel_enrollment(
    session: AsyncSession,
    *,
    enrollment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> EmailSequenceEnrollment:
    """Terminal cancel — no resume. Pending step rows get skipped."""
    enrollment = await get_enrollment(session, enrollment_id=enrollment_id)
    if enrollment.is_terminal:
        return enrollment
    now = datetime.now(UTC)
    enrollment.state = EnrollmentState.cancelled.value
    enrollment.state_changed_at = now
    await email_seq_da.skip_pending_enrollment_steps(
        session,
        enrollment_id=enrollment.id,
        skip_reason="enrollment_cancelled",
    )
    await session.commit()
    await session.refresh(enrollment)
    await audit.log(
        "email.sequence.enrollment_cancelled",
        entity_type="email_sequence_enrollment",
        entity_id=enrollment.id,
        after={"state": enrollment.state},
        user_id=actor_id,
    )
    return enrollment


__all__ = [
    "cancel_enrollment",
    "create_sequence",
    "delete_sequence",
    "enroll",
    "get_enrollment",
    "get_sequence",
    "get_sequence_with_steps",
    "list_enrollments",
    "list_sequences",
    "pause_enrollment",
    "resume_enrollment",
    "update_sequence",
]
