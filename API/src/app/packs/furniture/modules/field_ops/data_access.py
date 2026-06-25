"""Data-access layer for the field_ops pack module.

Pure query helpers — no transactions, no audit, no orchestration.
Leaf module; never imports a ``service.py``.

Operations:

  * Field visits (``fp_field_visits``)
      get_visit_by_id, list_visits_query, insert_visit,
      delete_visit_row
  * Field visit photos (``fp_field_visit_photos``)
      list_photos_for_visit, insert_photo
  * Cross-module verifier (against ``fp_custom_orders``)
      custom_order_exists_in_org — narrow projection existence check
        used by the visit-create validator
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment
from src.app.packs.furniture.modules.custom_orders.models import CustomOrder
from src.app.packs.furniture.modules.field_ops.models import (
    FieldVisit,
    FieldVisitPhoto,
    FieldVisitPurpose,
)


# --- Field visits -------------------------------------------------------


async def get_visit_by_id(
    session: AsyncSession, visit_id: uuid.UUID
) -> Optional[FieldVisit]:
    """Single-row read by PK. ``None`` on miss."""
    return (
        await session.execute(
            select(FieldVisit).where(FieldVisit.id == visit_id)
        )
    ).scalar_one_or_none()


async def list_visits_query(
    session: AsyncSession,
    *,
    assigned_to_id: Optional[uuid.UUID] = None,
    purpose: Optional[FieldVisitPurpose] = None,
    completed: Optional[bool] = None,
    custom_order_id: Optional[uuid.UUID] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[FieldVisit], int]:
    """Filtered paginated list of field visits, newest first.

    ``completed=True`` returns visits with non-NULL ``completed_at``;
    ``False`` returns still-open visits; ``None`` returns both.
    ``assigned_to_id`` joins via the underlying appointment so the
    staff portal can pull only "my visits" cheaply.
    """
    filters: list[Any] = []
    if purpose is not None:
        filters.append(FieldVisit.purpose == purpose)
    if completed is True:
        filters.append(FieldVisit.completed_at.is_not(None))
    elif completed is False:
        filters.append(FieldVisit.completed_at.is_(None))
    if custom_order_id is not None:
        filters.append(FieldVisit.custom_order_id == custom_order_id)

    base = select(FieldVisit)
    count_stmt = select(func.count()).select_from(FieldVisit)

    if assigned_to_id is not None:
        base = base.join(
            Appointment, Appointment.id == FieldVisit.appointment_id
        ).where(Appointment.assigned_to_id == assigned_to_id)
        count_stmt = count_stmt.join(
            Appointment, Appointment.id == FieldVisit.appointment_id
        ).where(Appointment.assigned_to_id == assigned_to_id)

    if filters:
        where = and_(*filters)
        base = base.where(where)
        count_stmt = count_stmt.where(where)

    base = base.order_by(FieldVisit.created_at.desc())
    total = (await session.execute(count_stmt)).scalar_one()
    offset = (page - 1) * size
    rows = (
        (await session.execute(base.offset(offset).limit(size)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


def insert_visit(session: AsyncSession, visit: FieldVisit) -> None:
    """Register an already-constructed FieldVisit for INSERT."""
    session.add(visit)


async def delete_visit_row(
    session: AsyncSession, visit: FieldVisit
) -> None:
    """Mark a FieldVisit row for DELETE. Caller commits."""
    await session.delete(visit)


# --- Field visit photos -------------------------------------------------


async def list_photos_for_visit(
    session: AsyncSession, visit_id: uuid.UUID
) -> list[FieldVisitPhoto]:
    """All photos for one visit, newest first."""
    stmt = (
        select(FieldVisitPhoto)
        .where(FieldVisitPhoto.visit_id == visit_id)
        .order_by(FieldVisitPhoto.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


def insert_photo(
    session: AsyncSession, photo: FieldVisitPhoto
) -> None:
    """Register an already-constructed FieldVisitPhoto for INSERT."""
    session.add(photo)


# --- Cross-module verifier ----------------------------------------------


async def custom_order_exists_in_org(
    session: AsyncSession, custom_order_id: uuid.UUID
) -> bool:
    """Narrow-column existence check against ``fp_custom_orders``.
    Used by the visit-create / update validator to reject out-of-org
    custom_order_id references with a friendly 422."""
    row = (
        await session.execute(
            select(CustomOrder.id).where(CustomOrder.id == custom_order_id)
        )
    ).scalar_one_or_none()
    return row is not None


__all__ = [
    "custom_order_exists_in_org",
    "delete_visit_row",
    "get_visit_by_id",
    "insert_photo",
    "insert_visit",
    "list_photos_for_visit",
    "list_visits_query",
]
