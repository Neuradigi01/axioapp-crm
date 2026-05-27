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
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.activities.models import Activity, ActivityType
from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.appointments.schemas import (
    AppointmentCreate,
    AppointmentUpdate,
)
from src.app.core.appointments.status_workflow import ALLOWED_TRANSITIONS
from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.core.users.models import OrganizationMember, User


# Server-side sort whitelist. Router validates via FastAPI Literal; the
# service resolves key → SQLA column without exposing attribute access.
_SORT_COLUMNS = {
    "scheduled_at": Appointment.scheduled_at,
    "created_at": Appointment.created_at,
    "last_activity_at": Appointment.last_activity_at,
}


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

    # State-machine enforcement: only allow status transitions declared
    # in `ALLOWED_TRANSITIONS`. Identity transitions (X → X) are rejected
    # — a no-op status change shouldn't ride along on a PATCH. Other
    # field changes can still go through without re-sending `status`.
    if "status" in changes and changes["status"] is not None:
        new_status = changes["status"]
        new_value = (
            new_status.value
            if isinstance(new_status, AppointmentStatus)
            else str(new_status)
        )
        current = appt.status.value
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if new_value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"invalid appointment status transition "
                    f"{current!r} → {new_value!r}"
                ),
            )

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
    sort: Literal[
        "scheduled_at", "created_at", "last_activity_at"
    ] = "scheduled_at",
    order: Literal["asc", "desc"] = "asc",
) -> list[Appointment]:
    """Calendar / list reading.

    - `from_dt` / `to_dt` — bound the `scheduled_at` window. Calendar
      views pass both; list views typically pass neither.
    - `assigned_to` / `status_filter` — exact-match scoping.
    - `sort` is server-whitelisted via `_SORT_COLUMNS`.
      `last_activity_at` ordering appends `NULLS LAST` so
      never-touched rows sink to the bottom of either direction.
    - Default `scheduled_at asc` matches the prior calendar default
      (upcoming first).

    Not paginated — the FE either passes a bounded `[from, to)` slice
    or filters down via assignee/status; per-day / per-week views
    never produce result sets large enough to warrant cursor paging.
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

    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


# --- Reschedule / reassign / bulk-action -----------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org.

    Same join + check as contacts/leads/walk-ins reassign services —
    keeps the cross-tenant guard uniform across modules."""
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
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def reschedule_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    org_id: uuid.UUID,
    scheduled_at: datetime,
    reason: str | None,
    actor_user_id: uuid.UUID | None,
) -> Appointment:
    """Shift an appointment's slot without going through the full edit
    form. Re-runs the conflict check against the new slot. Writes a
    dedicated `reschedule` audit activity (distinct from the edit-time
    `note` activity that `update_appointment` writes) so the timeline
    can render it with a calendar-clock icon.

    404 if not found. 422 if status is terminal (`completed`) or if
    the new slot collides. 409 on conflict via `find_conflicts`."""
    appt = await get_appointment(session, appointment_id)
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="appointment not found",
        )

    # Don't allow rescheduling a completed appointment — it's terminal.
    # Cancelled / no_show are still reschedulable (rebook the slot;
    # state-machine handles the implicit transition back to scheduled
    # if the caller wants that).
    if appt.status == AppointmentStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot reschedule a completed appointment",
        )

    if scheduled_at == appt.scheduled_at:
        # No-op — return as-is. The FE shouldn't have submitted but
        # don't error on accidental double-submits.
        return appt

    # Conflict re-check at the new slot (only if the appointment is
    # currently blocking — cancelled/no_show wouldn't collide with
    # anything because we exclude self via exclude_id).
    if appt.status not in _NON_BLOCKING_STATUSES:
        conflicts = await find_conflicts(
            session,
            assigned_to_id=appt.assigned_to_id,
            scheduled_at=scheduled_at,
            duration_min=appt.duration_min,
            exclude_id=appt.id,
        )
        if conflicts:
            _raise_conflict_409(conflicts)

    before = _snapshot(appt)
    old_at = appt.scheduled_at
    appt.scheduled_at = scheduled_at
    session.add(
        Activity(
            org_id=org_id,
            entity_type=_APPT_ENTITY,
            entity_id=appt.id,
            type=ActivityType.reschedule,
            payload={
                "from": old_at.isoformat(),
                "to": scheduled_at.isoformat(),
                "reason": reason,
            },
            user_id=actor_user_id,
        )
    )
    await session.commit()
    await session.refresh(appt)

    await audit.log(
        "appointments.rescheduled",
        entity_type=_APPT_ENTITY,
        entity_id=appt.id,
        before=before,
        after=_snapshot(appt),
    )
    return appt


async def reassign_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> Appointment:
    """Single-row reassign. `None` clears the owner (set NULL on
    `assigned_to_id` — wait, appointments require an owner). Actually
    appointments.assigned_to_id is NOT NULL, so `None` is rejected
    upstream by the Pydantic schema's required-ness check at the
    router. We still accept Optional here so the type signature
    matches the bulk variant; the router enforces non-null."""
    appt = await get_appointment(session, appointment_id)
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="appointment not found",
        )
    if assigned_to_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="appointments require an owner; assigned_to_id cannot be null",
        )
    await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    before_id = appt.assigned_to_id
    if before_id == assigned_to_id:
        return appt

    before = _snapshot(appt)
    appt.assigned_to_id = assigned_to_id
    session.add(
        Activity(
            org_id=org_id,
            entity_type=_APPT_ENTITY,
            entity_id=appt.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(
                from_id=before_id, to_id=assigned_to_id, note=note
            ),
            user_id=actor_user_id,
        )
    )
    await session.commit()
    await session.refresh(appt)

    await audit.log(
        "appointments.reassigned",
        entity_type=_APPT_ENTITY,
        entity_id=appt.id,
        before=before,
        after=_snapshot(appt),
    )
    return appt


async def bulk_reassign_appointments(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Bulk variant of `reassign_appointment`. Appointments require an
    owner, so `assigned_to_id` must be non-null — the router enforces
    this via schema. Per-row processing because rows with the same
    owner are skipped (no-op, not an error)."""
    if assigned_to_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="appointments require an owner; assigned_to_id cannot be null",
        )
    await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    reassigned = 0
    for aid in ids:
        appt = await get_appointment(session, aid)
        if appt is None:
            continue
        if appt.assigned_to_id == assigned_to_id:
            continue
        before_id = appt.assigned_to_id
        appt.assigned_to_id = assigned_to_id
        session.add(
            Activity(
                org_id=org_id,
                entity_type=_APPT_ENTITY,
                entity_id=appt.id,
                type=ActivityType.reassign,
                payload=_reassign_payload(
                    from_id=before_id, to_id=assigned_to_id, note=note
                ),
                user_id=actor_user_id,
            )
        )
        reassigned += 1

    await session.commit()
    return reassigned


async def bulk_cancel_appointments(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    reason: str | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[int, int]:
    """Move every row currently in `scheduled` to `cancelled`. Rows in
    any other state are skipped (counted as `skipped`) — same partial
    success semantic as walk-ins bulk-checkout. Each cancelled row
    gets an audit `status_change` activity carrying the reason."""
    cancelled = 0
    skipped = 0
    for aid in ids:
        appt = await get_appointment(session, aid)
        if appt is None:
            continue
        if appt.org_id != org_id:
            # Defence-in-depth: ORM filter scopes SELECTs but skip
            # anything that somehow slipped through.
            continue
        if appt.status != AppointmentStatus.scheduled:
            skipped += 1
            continue
        before_status = appt.status.value
        appt.status = AppointmentStatus.cancelled
        session.add(
            Activity(
                org_id=org_id,
                entity_type=_APPT_ENTITY,
                entity_id=appt.id,
                type=ActivityType.status_change,
                payload={
                    "from": before_status,
                    "to": AppointmentStatus.cancelled.value,
                    "reason": reason,
                },
                user_id=actor_user_id,
            )
        )
        cancelled += 1

    await session.commit()
    return cancelled, skipped


__all__ = [
    "AppointmentStatus",
    "bulk_cancel_appointments",
    "bulk_reassign_appointments",
    "create_appointment",
    "delete_appointment",
    "find_conflicts",
    "get_appointment",
    "list_appointments",
    "reassign_appointment",
    "reschedule_appointment",
    "update_appointment",
]
