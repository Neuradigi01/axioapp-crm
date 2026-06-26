"""Data-access layer for the email-sequences module.

Pure query helpers — no transactions, no audit. Leaf module; never
imports a `service.py`.

Post-Step-10 of ``tasks/template-library`` the sequence builder
accepts a list of ``template_id`` values (one per step). Each must:

  * point at a row in ``tbl_message_templates`` (post-migration the
    FK lives there);
  * carry ``channel='email'`` (sequences are email-only at v1);
  * be live (not archived).

``list_valid_email_template_ids`` returns the subset of supplied ids
that satisfy the above. Sequence service compares the result against
the input to raise a clear 400 listing the offending ids.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.email_sequences.models import (
    EmailSequence,
    EmailSequenceEnrollment,
    EmailSequenceEnrollmentStep,
    EmailSequenceStep,
    EnrollmentState,
)
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateInternalStatus,
)


async def list_valid_email_template_ids(
    session: AsyncSession, template_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Return the subset of ``template_ids`` that point at live
    email templates in the current org. Tenant scoping is applied by
    the ``do_orm_execute`` listener."""
    if not template_ids:
        return set()
    rows = (
        await session.execute(
            select(MessageTemplate.id).where(
                MessageTemplate.id.in_(set(template_ids)),
                MessageTemplate.channel == ConversationChannel.email,
                MessageTemplate.internal_status != TemplateInternalStatus.archived,
            )
        )
    ).all()
    return {r.id for r in rows}


# --- sequences ----------------------------------------------------------


async def list_steps_in_order(
    session: AsyncSession, *, sequence_id: uuid.UUID
) -> list[EmailSequenceStep]:
    """All steps for a sequence in `step_order` ascending."""
    rows = (
        await session.execute(
            select(EmailSequenceStep)
            .where(EmailSequenceStep.sequence_id == sequence_id)
            .order_by(EmailSequenceStep.step_order.asc())
        )
    ).scalars().all()
    return list(rows)


async def count_sequences_filtered(
    session: AsyncSession,
    *,
    q: str | None,
    is_active: bool | None,
) -> int:
    """Count sequences matching the filters (soft-deleted excluded)."""
    filters: list[Any] = [EmailSequence.deleted_at.is_(None)]
    if is_active is not None:
        filters.append(EmailSequence.is_active.is_(is_active))
    if q:
        filters.append(EmailSequence.name.ilike(f"%{q}%"))
    result = await session.execute(
        select(func.count()).select_from(EmailSequence).where(*filters)
    )
    return int(result.scalar_one() or 0)


async def list_sequences_page(
    session: AsyncSession,
    *,
    q: str | None,
    is_active: bool | None,
    offset: int,
    limit: int,
) -> list[EmailSequence]:
    """Paginated sequences sorted by updated-at desc."""
    filters: list[Any] = [EmailSequence.deleted_at.is_(None)]
    if is_active is not None:
        filters.append(EmailSequence.is_active.is_(is_active))
    if q:
        filters.append(EmailSequence.name.ilike(f"%{q}%"))
    rows = (
        await session.execute(
            select(EmailSequence)
            .where(*filters)
            .order_by(EmailSequence.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def get_sequence_by_id(
    session: AsyncSession, sequence_id: uuid.UUID
) -> EmailSequence | None:
    """Raw sequence lookup — caller does the soft-delete + 404 check."""
    result = await session.execute(
        select(EmailSequence).where(EmailSequence.id == sequence_id)
    )
    return result.scalar_one_or_none()


def add_sequence(
    session: AsyncSession, sequence: EmailSequence
) -> EmailSequence:
    """Stage a new sequence row in the unit-of-work."""
    session.add(sequence)
    return sequence


def add_sequence_steps(
    session: AsyncSession, steps: list[EmailSequenceStep]
) -> None:
    """Bulk-stage step rows in the unit-of-work."""
    session.add_all(steps)


async def delete_steps_for_sequence(
    session: AsyncSession, sequence_id: uuid.UUID
) -> None:
    """Drop every `EmailSequenceStep` row for one sequence."""
    await session.execute(
        sa_delete(EmailSequenceStep).where(
            EmailSequenceStep.sequence_id == sequence_id
        )
    )


_NON_TERMINAL_STATES = (
    EnrollmentState.active.value,
    EnrollmentState.paused_on_reply.value,
    EnrollmentState.paused_manual.value,
)


async def count_non_terminal_enrollments(
    session: AsyncSession, sequence_id: uuid.UUID
) -> int:
    """Number of enrollments in `active` / `paused_*` state."""
    result = await session.execute(
        select(func.count())
        .select_from(EmailSequenceEnrollment)
        .where(
            EmailSequenceEnrollment.sequence_id == sequence_id,
            EmailSequenceEnrollment.state.in_(_NON_TERMINAL_STATES),
        )
    )
    return int(result.scalar_one() or 0)


# --- enrollments --------------------------------------------------------


async def list_active_enrollment_ids_for_contacts(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> dict[uuid.UUID, uuid.UUID]:
    """Map contact id → existing non-terminal enrollment id.

    Used by `enroll` to dedupe: a contact with a live enrollment for
    this sequence is skipped rather than re-enrolled.
    """
    if not contact_ids:
        return {}
    rows = (
        await session.execute(
            select(
                EmailSequenceEnrollment.contact_id,
                EmailSequenceEnrollment.id,
            ).where(
                EmailSequenceEnrollment.sequence_id == sequence_id,
                EmailSequenceEnrollment.contact_id.in_(set(contact_ids)),
                EmailSequenceEnrollment.state.in_(_NON_TERMINAL_STATES),
            )
        )
    ).all()
    return {r.contact_id: r.id for r in rows}


def add_enrollment(
    session: AsyncSession, enrollment: EmailSequenceEnrollment
) -> EmailSequenceEnrollment:
    """Stage an enrollment row in the unit-of-work."""
    session.add(enrollment)
    return enrollment


def add_enrollment_step(
    session: AsyncSession, step: EmailSequenceEnrollmentStep
) -> EmailSequenceEnrollmentStep:
    """Stage an enrollment-step row in the unit-of-work."""
    session.add(step)
    return step


async def get_enrollment_by_id(
    session: AsyncSession, enrollment_id: uuid.UUID
) -> EmailSequenceEnrollment | None:
    """Single enrollment lookup."""
    result = await session.execute(
        select(EmailSequenceEnrollment).where(
            EmailSequenceEnrollment.id == enrollment_id
        )
    )
    return result.scalar_one_or_none()


async def count_enrollments_filtered(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
    state: str | None,
) -> int:
    """Enrollment count for the list endpoint."""
    filters: list[Any] = []
    if sequence_id is not None:
        filters.append(EmailSequenceEnrollment.sequence_id == sequence_id)
    if contact_id is not None:
        filters.append(EmailSequenceEnrollment.contact_id == contact_id)
    if state is not None:
        filters.append(EmailSequenceEnrollment.state == state)
    result = await session.execute(
        select(func.count())
        .select_from(EmailSequenceEnrollment)
        .where(*filters)
    )
    return int(result.scalar_one() or 0)


async def list_enrollments_page(
    session: AsyncSession,
    *,
    sequence_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
    state: str | None,
    offset: int,
    limit: int,
) -> list[EmailSequenceEnrollment]:
    """Paginated enrollments sorted by enrolled-at desc."""
    filters: list[Any] = []
    if sequence_id is not None:
        filters.append(EmailSequenceEnrollment.sequence_id == sequence_id)
    if contact_id is not None:
        filters.append(EmailSequenceEnrollment.contact_id == contact_id)
    if state is not None:
        filters.append(EmailSequenceEnrollment.state == state)
    rows = (
        await session.execute(
            select(EmailSequenceEnrollment)
            .where(*filters)
            .order_by(EmailSequenceEnrollment.enrolled_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def skip_pending_enrollment_steps(
    session: AsyncSession,
    *,
    enrollment_id: uuid.UUID,
    skip_reason: str,
) -> None:
    """Mark every still-pending step row for an enrollment as skipped.

    Used by pause + cancel so the scheduler stops firing them.
    """
    await session.execute(
        EmailSequenceEnrollmentStep.__table__.update()
        .where(
            EmailSequenceEnrollmentStep.enrollment_id == enrollment_id,
            EmailSequenceEnrollmentStep.sent_at.is_(None),
            EmailSequenceEnrollmentStep.skipped.is_(False),
        )
        .values(skipped=True, skip_reason=skip_reason)
    )


__all__ = [
    "add_enrollment",
    "add_enrollment_step",
    "add_sequence",
    "add_sequence_steps",
    "count_enrollments_filtered",
    "count_non_terminal_enrollments",
    "count_sequences_filtered",
    "delete_steps_for_sequence",
    "get_enrollment_by_id",
    "get_sequence_by_id",
    "list_active_enrollment_ids_for_contacts",
    "list_enrollments_page",
    "list_sequences_page",
    "list_steps_in_order",
    "list_valid_email_template_ids",
    "skip_pending_enrollment_steps",
]
