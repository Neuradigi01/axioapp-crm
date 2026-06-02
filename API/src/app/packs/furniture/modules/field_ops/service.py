"""Service layer for the furniture-pack field-ops module.

Three concerns:

1. `create_visit` — wraps `appointments.create_appointment` and
   inserts an `fp_field_visits` row in the same session. We reuse the
   core appointments engine so calendars + conflict detection +
   contact-timeline notes all work as-is. The pack's only addition is
   the per-visit metadata (purpose, custom_order link, signature).

2. `complete_visit` — sets `completed_at`, optionally bumps the
   linked appointment to `status='completed'`, and optionally copies a
   list of measurements into the linked custom order (when one is
   linked). This is the staff-on-site flow: walk in, measure, mark
   complete, the office side sees the result.

3. Photos — uploaded via `StorageBackend`, URL persisted here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.shared.audit import log_entity_change
from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.appointments.service import (
    create_appointment as core_create_appointment,
)
from src.app.packs.furniture.modules.custom_orders.models import CustomOrder
from src.app.packs.furniture.modules.custom_orders.service import (
    add_measurement as co_add_measurement,
)
from src.app.packs.furniture.modules.custom_orders.schemas import (
    MeasurementCreate,
)
from src.app.packs.furniture.modules.field_ops.models import (
    FieldVisit,
    FieldVisitPhoto,
    FieldVisitPurpose,
)
from src.app.packs.furniture.modules.field_ops.schemas import (
    FieldVisitCompletePayload,
    FieldVisitCreate,
    FieldVisitUpdate,
)
from src.app.shared.storage import get_storage


# --- reads ----------------------------------------------------------------


async def list_visits(
    session: AsyncSession,
    *,
    assigned_to_id: Optional[uuid.UUID] = None,
    purpose: Optional[FieldVisitPurpose] = None,
    completed: Optional[bool] = None,
    custom_order_id: Optional[uuid.UUID] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[FieldVisit], int]:
    """Server-side filters.

    `completed=True` returns visits whose `completed_at IS NOT NULL`;
    `False` returns the still-open ones. `None` returns both.

    `assigned_to_id` joins via the underlying appointment so the staff
    portal can pull only "my visits" cheaply.
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
        # Join via appointments to filter by assignee.
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


async def get_visit(
    session: AsyncSession, visit_id: uuid.UUID
) -> FieldVisit:
    row = (
        await session.execute(
            select(FieldVisit).where(FieldVisit.id == visit_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="field visit not found",
        )
    return row


async def get_appointment_for_visit(
    session: AsyncSession, visit: FieldVisit
) -> Appointment:
    appt = (
        await session.execute(
            select(Appointment).where(Appointment.id == visit.appointment_id)
        )
    ).scalar_one_or_none()
    if appt is None:
        # Schema-level CASCADE means this should never happen, but the
        # caller wants an Appointment to merge into the response.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="appointment row missing for field visit",
        )
    return appt


# --- writes ---------------------------------------------------------------


async def create_visit(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: FieldVisitCreate,
) -> FieldVisit:
    """Create appointment + field-visit in one transaction."""
    if payload.custom_order_id is not None:
        await _ensure_custom_order_in_scope(session, payload.custom_order_id)

    # 1. Appointment first — core engine validates contact/user scope
    # and runs conflict detection.
    appt = await core_create_appointment(
        session,
        org_id=org_id,
        current_user_id=user_id,
        payload=payload.appointment,
    )

    # 2. Pack-specific visit row.
    visit = FieldVisit(
        org_id=org_id,
        appointment_id=appt.id,
        purpose=payload.purpose,
        custom_order_id=payload.custom_order_id,
        notes=payload.notes,
        custom_data=payload.custom_data,
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)

    await log_entity_change(
        action="field_visits.created",
        entity_type="field_visit",
        entity_id=visit.id,
        after={
            "purpose": visit.purpose.value,
            "appointment_id": str(visit.appointment_id),
            "custom_order_id": (
                str(visit.custom_order_id) if visit.custom_order_id else None
            ),
        },
        user_id=user_id,
    )
    return visit


async def update_visit(
    session: AsyncSession,
    *,
    visit_id: uuid.UUID,
    payload: FieldVisitUpdate,
) -> FieldVisit:
    visit = await get_visit(session, visit_id)
    if payload.custom_order_id is not None:
        await _ensure_custom_order_in_scope(session, payload.custom_order_id)

    changed = False
    for field in (
        "purpose",
        "custom_order_id",
        "notes",
        "signature_url",
        "custom_data",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(visit, field, value)
            changed = True
    if changed:
        await session.commit()
        await session.refresh(visit)
    return visit


async def delete_visit(
    session: AsyncSession, *, visit_id: uuid.UUID
) -> None:
    visit = await get_visit(session, visit_id)
    await session.delete(visit)
    await session.commit()


# --- complete -------------------------------------------------------------


async def complete_visit(
    session: AsyncSession,
    *,
    visit_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: FieldVisitCompletePayload,
) -> FieldVisit:
    """Mark visit complete; flip the appointment to `completed`; copy
    measurements back to the linked custom order if any were captured.
    """
    visit = await get_visit(session, visit_id)
    if visit.completed_at is not None:
        # Idempotent — don't re-write or double-copy measurements.
        return visit

    now = datetime.now(timezone.utc)
    visit.completed_at = now
    if payload.signature_url is not None:
        visit.signature_url = payload.signature_url
    if payload.notes is not None:
        # Append rather than overwrite — the original note from the
        # schedule still has value, the closing note is new info.
        if visit.notes:
            visit.notes = f"{visit.notes}\n\n[closed] {payload.notes}"
        else:
            visit.notes = payload.notes

    appt = await get_appointment_for_visit(session, visit)
    appt.status = AppointmentStatus.completed
    await session.commit()
    await session.refresh(visit)

    # Copy measurements back to the linked custom order, if any.
    copied: list[uuid.UUID] = []
    if visit.custom_order_id is not None and payload.measurements:
        for m in payload.measurements:
            row = await co_add_measurement(
                session,
                order_id=visit.custom_order_id,
                payload=MeasurementCreate(
                    item_label=m.item_label,
                    length_cm=m.length_cm,
                    width_cm=m.width_cm,
                    height_cm=m.height_cm,
                    notes=m.notes,
                ),
            )
            copied.append(row.id)

    await audit.log(
        "field_visits.completed",
        entity_type="field_visit",
        entity_id=visit.id,
        before={"completed_at": None},
        after={
            "completed_at": now.isoformat(),
            "measurements_copied": [str(i) for i in copied],
        },
        user_id=user_id,
    )
    return visit


# --- photos ---------------------------------------------------------------


async def list_photos(
    session: AsyncSession, *, visit_id: uuid.UUID
) -> list[FieldVisitPhoto]:
    stmt = (
        select(FieldVisitPhoto)
        .where(FieldVisitPhoto.visit_id == visit_id)
        .order_by(FieldVisitPhoto.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def add_photo(
    session: AsyncSession,
    *,
    visit_id: uuid.UUID,
    data: bytes,
    content_type: str,
    file_extension: str,
    caption: Optional[str] = None,
) -> FieldVisitPhoto:
    visit = await get_visit(session, visit_id)
    photo_id = uuid.uuid4()
    storage_path = (
        f"{visit.org_id}/field_visits/{visit.id}/photo-{photo_id}.{file_extension}"
    )
    ref = get_storage().put(storage_path, data, content_type=content_type)

    photo = FieldVisitPhoto(
        id=photo_id,
        org_id=visit.org_id,
        visit_id=visit.id,
        url=ref.url,
        caption=caption,
        taken_at=datetime.now(timezone.utc),
    )
    session.add(photo)
    await session.commit()
    await session.refresh(photo)
    return photo


# --- helpers --------------------------------------------------------------


async def _ensure_custom_order_in_scope(
    session: AsyncSession, custom_order_id: uuid.UUID
) -> None:
    row = (
        await session.execute(
            select(CustomOrder.id).where(CustomOrder.id == custom_order_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"custom_order_id {custom_order_id} not found in this org",
        )


__all__ = [
    "add_photo",
    "complete_visit",
    "create_visit",
    "delete_visit",
    "get_appointment_for_visit",
    "get_visit",
    "list_photos",
    "list_visits",
    "update_visit",
]
