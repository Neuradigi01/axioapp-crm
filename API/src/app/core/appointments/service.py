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
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.users import service as users_service
from src.app.core.activities.models import ActivityType
from src.app.core.appointments import data_access as _da
from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.appointments.schemas import (
    AppointmentCreate,
    AppointmentUpdate,
)
from src.app.core.appointments.status_workflow import ALLOWED_TRANSITIONS
from src.app.core.notifications import service as notifications
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.context import get_context
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found


_APPT_ENTITY = "appointment"
# Statuses that DON'T block a slot — the assignee can have another
# appointment overlapping a cancelled or no-show one.
_NON_BLOCKING_STATUSES = (
    AppointmentStatus.cancelled,
    AppointmentStatus.no_show,
)


_SNAPSHOT_FIELDS = (
    "id",
    "contact_id",
    "title",
    "purpose",
    "scheduled_at",
    "duration_min",
    "location",
    "status",
    "assigned_to_id",
    "custom_data",
)


def _snapshot(a: Appointment) -> dict[str, Any]:
    return snapshot(a, fields=_SNAPSHOT_FIELDS)


# --- Notification helpers --------------------------------------------------
#
# Three notification types fire from this module:
#   - appointment.assigned    — new appointment OR reassign
#   - appointment.rescheduled — slot moved
#   - appointment.cancelled   — status flipped to cancelled
#
# The notifications service opens its own session and is non-raising, so
# these helpers are safe to call after the main transaction commits.
# A failure to deliver never rolls back the appointment write.


async def _resolve_contact_name(
    session: AsyncSession, contact_id: uuid.UUID | None
) -> str | None:
    if contact_id is None:
        return None
    return await _da.get_contact_name(session, contact_id)


def _human_scheduled_at(when: datetime) -> str:
    # `Fri Jun 06, 10:00 AM` — readable in any locale we currently
    # serve, short enough for a notification body.
    return when.strftime("%a %b %d, %I:%M %p")


async def _notify_appointment_event(
    *,
    session: AsyncSession,
    appt: Appointment,
    org_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    event_type: str,
) -> None:
    """Build the (title, body, payload) for an appointment event and
    forward to `notifications.notify`. Safe to call after commit; any
    DB/socket failure is swallowed by `notify` itself.
    """
    contact_name = await _resolve_contact_name(session, appt.contact_id)
    when_human = _human_scheduled_at(appt.scheduled_at)

    if event_type == "appointment.assigned":
        title = f"New appointment: {appt.title}"
        parts = [f"Scheduled {when_human}"]
        if contact_name:
            parts.append(f"with {contact_name}")
        if appt.location:
            parts.append(f"at {appt.location}")
        body = " ".join(parts)
    elif event_type == "appointment.rescheduled":
        title = f"Appointment rescheduled: {appt.title}"
        body = f"Moved to {when_human}"
    elif event_type == "appointment.cancelled":
        title = f"Appointment cancelled: {appt.title}"
        if contact_name:
            body = f"{contact_name} on {when_human} was cancelled"
        else:
            body = f"{when_human} was cancelled"
    else:
        return  # unknown type, nothing to send

    payload: dict[str, Any] = {
        "appointment_id": str(appt.id),
        "contact_id": str(appt.contact_id) if appt.contact_id else None,
        "contact_name": contact_name,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "title": appt.title,
        "location": appt.location,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
    }

    await notifications.notify(
        org_id=org_id,
        user_id=recipient_user_id,
        type=event_type,
        title=title,
        body=body,
        payload=payload,
    )


# --- in-scope existence helpers ---


async def _ensure_contact_in_scope(
    session: AsyncSession, contact_id: uuid.UUID
) -> None:
    if not await _da.contact_exists(session, contact_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contact_id {contact_id} not found in this org",
        )


async def _ensure_user_in_scope(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    user = await users_service.get_user_by_uuid(session, user_id)
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

    candidates = await _da.find_overlapping_appointments(
        session,
        assigned_to_id=assigned_to_id,
        scheduled_at_lt=new_end,
        non_blocking_statuses=_NON_BLOCKING_STATUSES,
        exclude_id=exclude_id,
    )

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
    return await _da.get_appointment_by_id(session, appointment_id)


async def create_appointment(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: AppointmentCreate,
) -> Appointment:
    await _ensure_contact_in_scope(session, payload.contact_id)
    await _ensure_user_in_scope(session, payload.assigned_to_id)
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_APPT_ENTITY,
        payload=payload.custom_data,
        require_all_required=True,
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
    _da.insert_appointment(session, appt)
    await session.commit()
    await session.refresh(appt)

    await log_entity_change(
        action="appointments.created",
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

    # Notify the assignee — only when someone else booked for them.
    # Suppression avoids self-spam when a user books their own slot.
    if appt.assigned_to_id != current_user_id:
        await _notify_appointment_event(
            session=session,
            appt=appt,
            org_id=org_id,
            recipient_user_id=appt.assigned_to_id,
            actor_user_id=current_user_id,
            event_type="appointment.assigned",
        )

    return appt


async def update_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    current_user_id: uuid.UUID,
    payload: AppointmentUpdate,
) -> Appointment:
    appt = ensure_found(await get_appointment(session, appointment_id), entity="appointment")

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
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_APPT_ENTITY,
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

    await log_entity_change(
        action="appointments.updated",
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

    # Notify on a status-flip to `cancelled`. Suppressed when the
    # canceller is the owner themselves — they don't need to hear
    # about their own action.
    if (
        "status" in changes
        and changes["status"] is not None
        and appt.status == AppointmentStatus.cancelled
        and appt.assigned_to_id != current_user_id
    ):
        # `org_id` isn't a parameter to this function — pull it from the
        # request context (the auth dependency populates it on every
        # /user route).
        ctx = get_context()
        if ctx.org_id is not None:
            await _notify_appointment_event(
                session=session,
                appt=appt,
                org_id=ctx.org_id,
                recipient_user_id=appt.assigned_to_id,
                actor_user_id=current_user_id,
                event_type="appointment.cancelled",
            )

    return appt


async def delete_appointment(
    session: AsyncSession, *, appointment_id: uuid.UUID
) -> None:
    appt = ensure_found(await get_appointment(session, appointment_id), entity="appointment")
    before = _snapshot(appt)
    appt_uuid = appt.id
    await _da.delete_appointment(session, appt)
    await session.commit()

    await log_entity_change(
        action="appointments.deleted",
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
    return await _da.list_appointments_query(
        session,
        from_dt=from_dt,
        to_dt=to_dt,
        assigned_to=assigned_to,
        status_filter=status_filter,
        sort=sort,
        order=order,
    )


# --- Reschedule / reassign / bulk-action -----------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org.

    Same join + check as contacts/leads/walk-ins reassign services —
    keeps the cross-tenant guard uniform across modules."""
    if not await _da.user_has_active_membership(
        session, org_id=org_id, user_uuid=user_uuid
    ):
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
    appt = ensure_found(await get_appointment(session, appointment_id), entity="appointment")

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
    await activities.record_in_session(
        session,
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
    await session.commit()
    await session.refresh(appt)

    await audit.log(
        "appointments.rescheduled",
        entity_type=_APPT_ENTITY,
        entity_id=appt.id,
        before=before,
        after=_snapshot(appt),
    )

    # Reschedule notifies the assignee regardless of who acted — even
    # a self-reschedule lands in their inbox as a paper trail.
    await _notify_appointment_event(
        session=session,
        appt=appt,
        org_id=org_id,
        recipient_user_id=appt.assigned_to_id,
        actor_user_id=actor_user_id,
        event_type="appointment.rescheduled",
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
    appt = ensure_found(await get_appointment(session, appointment_id), entity="appointment")
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
    await activities.record_in_session(
        session,
        org_id=org_id,
        entity_type=_APPT_ENTITY,
        entity_id=appt.id,
        type=ActivityType.reassign,
        payload=_reassign_payload(
            from_id=before_id, to_id=assigned_to_id, note=note
        ),
        user_id=actor_user_id,
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

    # Notify the new owner — only when the reassign was done by
    # someone else. (Self-reassign is rare but possible via the API.)
    if assigned_to_id != actor_user_id:
        await _notify_appointment_event(
            session=session,
            appt=appt,
            org_id=org_id,
            recipient_user_id=assigned_to_id,
            actor_user_id=actor_user_id,
            event_type="appointment.assigned",
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
    # Collect the appts we actually moved so we can fan out
    # notifications after the commit lands. Keeping the list in memory
    # is fine — bulk reassigns are typically <100 rows.
    moved: list[Appointment] = []
    for aid in ids:
        appt = await get_appointment(session, aid)
        if appt is None:
            continue
        if appt.assigned_to_id == assigned_to_id:
            continue
        before_id = appt.assigned_to_id
        appt.assigned_to_id = assigned_to_id
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type=_APPT_ENTITY,
            entity_id=appt.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(
                from_id=before_id, to_id=assigned_to_id, note=note
            ),
            user_id=actor_user_id,
        )
        reassigned += 1
        moved.append(appt)

    await session.commit()

    # One notification per moved row for the new owner. Same
    # self-spam suppression as the single reassign path.
    if assigned_to_id != actor_user_id:
        for appt in moved:
            await _notify_appointment_event(
                session=session,
                appt=appt,
                org_id=org_id,
                recipient_user_id=assigned_to_id,
                actor_user_id=actor_user_id,
                event_type="appointment.assigned",
            )

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
        await activities.record_in_session(
            session,
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
