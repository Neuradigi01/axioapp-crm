"""Service layer for the appointments module.

Responsibilities:

1. CRUD against the `appointments` row with two cross-cutting checks
   on every write:
   - `contact_id` and `assigned_to_id` belong to the active tenant.
   - `custom_data` validates against `custom_field_definitions` for
     `entity_type='appointment'` (same engine contacts and leads use).
2. Conflict detection: a service-level overlap query against
   `(assigned_to_id, scheduled_at)` rejecting any new or rescheduled
   appointment that would double-book the assignee. Cancelled and
   no-show appointments don't block the slot. Implemented as a
   pre-filter on `scheduled_at < new_end` followed by a Python check
   of each candidate's end-time so we don't have to put
   interval-arithmetic into SQL.
3. Activity logging on create and on reschedule (when `scheduled_at`
   changes). The activity is attached to the contact, not the
   appointment, so it shows up on the contact's timeline tab — the
   primary surface where users look for "what's coming up with this
   customer".
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.activities.models import ActivityType
from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.appointments.schemas import (
    AppointmentCreate,
    AppointmentUpdate,
)
from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.core.users.models import User


_APPT_ENTITY = "appointment"
# Statuses that DON'T block a slot — the assignee can have another
# appointment overlapping a cancelled or no-show one.
_NON_BLOCKING_STATUSES = (
    AppointmentStatus.cancelled,
    AppointmentStatus.no_show,
)


def _snapshot(a: Appointment) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "contact_id": str(a.contact_id),
        "title": a.title,
        "purpose": a.purpose,
        "scheduled_at": a.scheduled_at.isoformat(),
        "duration_min": a.duration_min,
        "location": a.location,
        "status": a.status.value,
        "assigned_to_id": str(a.assigned_to_id),
        "custom_data": a.custom_data,
    }


# --- custom_data validation (mirrors contacts/leads — same engine) ---


async def _load_field_defs(
    session: AsyncSession,
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == _APPT_ENTITY
        )
    )
    return {row.field_key: row for row in result.scalars()}


def _coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    if value is None:
        return None
    if field_type in (
        FieldType.text,
        FieldType.phone,
        FieldType.email,
        FieldType.select,
    ):
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected string",
            )
        return value
    if field_type is FieldType.multiselect:
        if not isinstance(value, list) or not all(
            isinstance(v, str) for v in value
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected list of strings",
            )
        return value
    if field_type in (FieldType.number, FieldType.currency):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected number",
            )
        return value
    if field_type is FieldType.boolean:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected boolean",
            )
        return value
    if field_type is FieldType.date:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO date string",
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO date",
            ) from exc
        return value
    if field_type is FieldType.datetime:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO datetime string",
            )
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO datetime",
            ) from exc
        return value
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled field_type {field_type!r}",
    )


async def _validate_custom_data(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    require_all_required: bool,
) -> dict[str, Any]:
    defs = await _load_field_defs(session)

    unknown = set(payload) - set(defs)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "custom_data contains keys not defined for entity "
                f"'appointment': {sorted(unknown)}"
            ),
        )

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        cleaned[key] = _coerce_value(defs[key].field_type, key, value)

    if require_all_required:
        missing = [
            key
            for key, defn in defs.items()
            if defn.is_required and (key not in cleaned or cleaned[key] is None)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data missing required keys: {sorted(missing)}",
            )
    return cleaned


# --- in-scope existence helpers ---


async def _ensure_contact_in_scope(
    session: AsyncSession, contact_id: uuid.UUID
) -> None:
    contact = (
        await session.execute(select(Contact.id).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contact_id {contact_id} not found in this org",
        )


async def _ensure_user_in_scope(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    user = (
        await session.execute(select(User.legacy_uuid).where(User.legacy_uuid == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"assigned_to_id {user_id} not found in this org",
        )


# --- conflict detection ---


async def find_conflicts(
    session: AsyncSession,
    *,
    assigned_to_id: uuid.UUID,
    scheduled_at: datetime,
    duration_min: int,
    exclude_id: Optional[uuid.UUID] = None,
) -> list[uuid.UUID]:
    """Return ids of appointments that overlap the proposed slot for the
    same assignee. Cancelled / no-show appointments don't block.

    Pre-filters in SQL by `scheduled_at < proposed_end` and then checks
    each candidate's actual end (`scheduled_at + duration_min`) in
    Python — cheaper than interval arithmetic inside SQLAlchemy and
    accurate even for differing durations across rows.
    """
    new_end = scheduled_at + timedelta(minutes=duration_min)

    stmt = (
        select(Appointment)
        .where(Appointment.assigned_to_id == assigned_to_id)
        .where(Appointment.status.not_in(_NON_BLOCKING_STATUSES))
        .where(Appointment.scheduled_at < new_end)
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    candidates = (await session.execute(stmt)).scalars().all()

    conflicts: list[uuid.UUID] = []
    for c in candidates:
        candidate_end = c.scheduled_at + timedelta(minutes=c.duration_min)
        if candidate_end > scheduled_at:
            conflicts.append(c.id)
    return conflicts


def _raise_conflict_409(conflicts: list[uuid.UUID]) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "success": False,
            "message": "appointment conflicts with existing appointment(s)",
            "conflicts": [str(cid) for cid in conflicts],
        },
    )


# --- CRUD ---


async def get_appointment(
    session: AsyncSession, appointment_id: uuid.UUID
) -> Optional[Appointment]:
    result = await session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    return result.scalar_one_or_none()


async def create_appointment(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: AppointmentCreate,
) -> Appointment:
    await _ensure_contact_in_scope(session, payload.contact_id)
    await _ensure_user_in_scope(session, payload.assigned_to_id)
    cleaned_custom = await _validate_custom_data(
        session, payload=payload.custom_data, require_all_required=True
    )

    conflicts = await find_conflicts(
        session,
        assigned_to_id=payload.assigned_to_id,
        scheduled_at=payload.scheduled_at,
        duration_min=payload.duration_min,
    )
    if conflicts:
        _raise_conflict_409(conflicts)

    appt = Appointment(
        org_id=org_id,
        contact_id=payload.contact_id,
        title=payload.title,
        purpose=payload.purpose,
        scheduled_at=payload.scheduled_at,
        duration_min=payload.duration_min,
        location=payload.location,
        assigned_to_id=payload.assigned_to_id,
        status=AppointmentStatus.scheduled,
        custom_data=cleaned_custom,
    )
    session.add(appt)
    await session.commit()
    await session.refresh(appt)

    await audit.log(
        "appointments.created",
        entity_type="appointment",
        entity_id=appt.id,
        after=_snapshot(appt),
    )
    # Surface on the contact's timeline so it's discoverable.
    await activities.log(
        entity_type="contact",
        entity_id=appt.contact_id,
        type=ActivityType.note,
        payload={
            "text": (
                f"Appointment scheduled: {appt.title} on "
                f"{appt.scheduled_at.isoformat()}"
            ),
        },
        user_id=current_user_id,
    )
    return appt


async def update_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: AppointmentUpdate,
) -> Appointment:
    appt = await get_appointment(session, appointment_id)
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="appointment not found",
        )

    before = _snapshot(appt)
    changes = payload.model_dump(exclude_unset=True)

    # In-scope checks for any FKs being updated.
    if "assigned_to_id" in changes and changes["assigned_to_id"] is not None:
        await _ensure_user_in_scope(session, changes["assigned_to_id"])

    if "custom_data" in changes:
        changes["custom_data"] = await _validate_custom_data(
            session,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )

    # Conflict re-check if anything time/assignee-relevant changed.
    time_changed = (
        "scheduled_at" in changes
        or "duration_min" in changes
        or "assigned_to_id" in changes
    )
    if time_changed:
        new_scheduled = changes.get("scheduled_at", appt.scheduled_at)
        new_duration = changes.get("duration_min", appt.duration_min)
        new_assignee = changes.get("assigned_to_id", appt.assigned_to_id)
        # Honour the incoming status: if the caller is marking this row
        # cancelled/no_show in the same PATCH, it's no longer blocking
        # and we shouldn't check conflicts for it.
        new_status = changes.get("status", appt.status)
        if new_status not in _NON_BLOCKING_STATUSES:
            conflicts = await find_conflicts(
                session,
                assigned_to_id=new_assignee,
                scheduled_at=new_scheduled,
                duration_min=new_duration,
                exclude_id=appt.id,
            )
            if conflicts:
                _raise_conflict_409(conflicts)

    old_scheduled = appt.scheduled_at
    for key, value in changes.items():
        setattr(appt, key, value)
    await session.commit()
    await session.refresh(appt)

    await audit.log(
        "appointments.updated",
        entity_type="appointment",
        entity_id=appt.id,
        before=before,
        after=_snapshot(appt),
    )
    if "scheduled_at" in changes and appt.scheduled_at != old_scheduled:
        await activities.log(
            entity_type="contact",
            entity_id=appt.contact_id,
            type=ActivityType.note,
            payload={
                "text": (
                    f"Appointment rescheduled: {appt.title} → "
                    f"{appt.scheduled_at.isoformat()}"
                ),
            },
            user_id=current_user_id,
        )
    return appt


async def delete_appointment(
    session: AsyncSession, *, appointment_id: uuid.UUID
) -> None:
    appt = await get_appointment(session, appointment_id)
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="appointment not found",
        )
    before = _snapshot(appt)
    appt_uuid = appt.id
    await session.delete(appt)
    await session.commit()

    await audit.log(
        "appointments.deleted",
        entity_type="appointment",
        entity_id=appt_uuid,
        before=before,
    )


async def list_appointments(
    session: AsyncSession,
    *,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    assigned_to: Optional[uuid.UUID] = None,
    status_filter: Optional[AppointmentStatus] = None,
) -> list[Appointment]:
    """Calendar listing: flat array, sorted by `scheduled_at`.

    Range is intentionally not paginated — frontends pass a bounded
    `[from, to)` window and want every appointment that overlaps it.
    Per-day / per-week views never produce result sets large enough to
    warrant cursor pagination.
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
    stmt = stmt.order_by(Appointment.scheduled_at.asc(), Appointment.id.asc())

    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


__all__ = [
    "AppointmentStatus",
    "create_appointment",
    "delete_appointment",
    "find_conflicts",
    "get_appointment",
    "list_appointments",
    "update_appointment",
]
