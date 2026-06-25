"""Data-access layer for the appointments module.

Pure query helpers — no transactions, no commits, no business
validations. Leaf module; never imports a ``service.py``.

Operations:

  * ``get_appointment_by_id`` — single-row read.
  * ``get_contact_name`` / ``contact_exists`` — cross-module lookups
    against ``tbl_contacts`` for appointment validation + notification
    body composition. Kept here (vs in contacts DAL) because they're
    appointments-specific shapes — narrow column projection and
    existence check, not the canonical "hydrate a contact" call.
  * ``find_overlapping_appointments`` — SQL pre-filter for the
    conflict-check service. Returns candidates with
    ``scheduled_at < new_end``; service does the Python end-time
    comparison.
  * ``list_appointments_query`` — calendar / list read, no pagination.
  * ``user_has_active_membership`` — verification query for the
    reassign target check (User ⋈ OrganizationMember).

The ``_SORT_COLUMNS`` whitelist lives here because the service-level
``Literal`` already prevents arbitrary attribute access; the column
mapping is just plumbing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.contacts.models import Contact
from src.app.core.users.models import OrganizationMember, User


_SORT_COLUMNS = {
    "scheduled_at": Appointment.scheduled_at,
    "created_at": Appointment.created_at,
    "last_activity_at": Appointment.last_activity_at,
}


async def get_appointment_by_id(
    session: AsyncSession, appointment_id: uuid.UUID
) -> Optional[Appointment]:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    return result.scalar_one_or_none()


def insert_appointment(session: AsyncSession, appointment: Appointment) -> None:
    """Register an already-constructed Appointment for INSERT. Caller
    commits."""
    session.add(appointment)


async def delete_appointment(
    session: AsyncSession, appointment: Appointment
) -> None:
    """Mark an Appointment row for DELETE. Caller commits."""
    await session.delete(appointment)


async def get_contact_name(
    session: AsyncSession, contact_id: uuid.UUID
) -> str | None:
    """Narrow-column projection of ``tbl_contacts.full_name`` for the
    notification body. ``None`` when the contact was deleted between
    the appointment write and the post-commit notification."""
    return (
        await session.execute(
            select(Contact.full_name).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()


async def contact_exists(
    session: AsyncSession, contact_id: uuid.UUID
) -> bool:
    """Existence check used by the appointment-create validator. The
    full hydrate isn't needed — the caller just decides 422 vs proceed."""
    row = (
        await session.execute(
            select(Contact.id).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    return row is not None


async def find_overlapping_appointments(
    session: AsyncSession,
    *,
    assigned_to_id: uuid.UUID,
    scheduled_at_lt: datetime,
    non_blocking_statuses: Sequence[AppointmentStatus],
    exclude_id: Optional[uuid.UUID] = None,
) -> list[Appointment]:
    """SELECT candidates whose ``scheduled_at`` falls before the
    proposed new end-time, for the same assignee, excluding statuses
    that don't block (cancelled / no_show) and an optional row to
    exclude (used by the rescheduler so the row doesn't conflict with
    itself).

    Service does the Python end-time check on each candidate.
    """
    stmt = (
        select(Appointment)
        .where(Appointment.assigned_to_id == assigned_to_id)
        .where(Appointment.status.not_in(non_blocking_statuses))
        .where(Appointment.scheduled_at < scheduled_at_lt)
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    return list((await session.execute(stmt)).scalars().all())


async def list_appointments_query(
    session: AsyncSession,
    *,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    assigned_to: Optional[uuid.UUID] = None,
    status_filter: Optional[AppointmentStatus] = None,
    sort: Literal[
        "scheduled_at", "created_at", "last_activity_at"
    ] = "scheduled_at",
    order: Literal["asc", "desc"] = "asc",
) -> list[Appointment]:
    """Calendar / list read. Not paginated by design — the FE either
    passes a bounded ``[from, to)`` window or filters down via
    assignee/status.

    ``last_activity_at`` ordering appends ``NULLS LAST`` so
    never-touched rows sink to the bottom in either direction.
    Default ``scheduled_at asc`` matches the prior calendar default
    (upcoming first).
    """
    filters: list[Any] = []
    if from_dt is not None:
        filters.append(Appointment.scheduled_at >= from_dt)
    if to_dt is not None:
        filters.append(Appointment.scheduled_at < to_dt)
    if assigned_to is not None:
        filters.append(Appointment.assigned_to_id == assigned_to)
    if status_filter is not None:
        filters.append(Appointment.status == status_filter)

    stmt = select(Appointment)
    if filters:
        stmt = stmt.where(and_(*filters))

    sort_col = _SORT_COLUMNS[sort]
    if sort == "last_activity_at":
        primary = (
            sort_col.asc().nulls_last()
            if order == "asc"
            else sort_col.desc().nulls_last()
        )
    else:
        primary = sort_col.asc() if order == "asc" else sort_col.desc()
    stmt = stmt.order_by(primary, Appointment.id.asc())

    return list((await session.execute(stmt)).scalars().all())


async def user_has_active_membership(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> bool:
    """True when ``user_uuid`` resolves to a User whose
    ``OrganizationMember`` row is active in ``org_id``. Used by reassign
    target validation — same join + check the contacts/leads/walk-ins
    reassigners use to keep the cross-tenant guard uniform across
    modules."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


__all__ = [
    "contact_exists",
    "delete_appointment",
    "find_overlapping_appointments",
    "get_appointment_by_id",
    "get_contact_name",
    "insert_appointment",
    "list_appointments_query",
    "user_has_active_membership",
]
