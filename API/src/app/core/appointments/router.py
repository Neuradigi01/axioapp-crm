"""HTTP routes for the appointments module.

  GET    /api/v1/appointments?from=&to=&assigned_to=&status=&sort=&order=
                                                              → flat array
  POST   /api/v1/appointments                                  → create (409 on conflict)
  GET    /api/v1/appointments/{id}
  PATCH  /api/v1/appointments/{id}                             → 409 on conflict
  DELETE /api/v1/appointments/{id}

Reads gated by `appointments.read`; writes by `appointments.write`.
Tenant scoping is automatic via the ORM filter on `TenantScoped`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import AppointmentStatus
from src.app.core.appointments.schemas import (
    AppointmentBulkCancel,
    AppointmentBulkCancelResult,
    AppointmentBulkDelete,
    AppointmentBulkDeleteResult,
    AppointmentBulkReassign,
    AppointmentBulkReassignResult,
    AppointmentCreate,
    AppointmentOut,
    AppointmentReassign,
    AppointmentReschedule,
    AppointmentUpdate,
)
from src.app.core.appointments.service import (
    bulk_cancel_appointments,
    bulk_delete_appointments,
    bulk_reassign_appointments,
    create_appointment,
    delete_appointment,
    get_appointment,
    list_appointments,
    reassign_appointment,
    reschedule_appointment,
    update_appointment,
)
from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.get("", response_model=list[AppointmentOut])
async def list_appointments_endpoint(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    assigned_to: uuid.UUID | None = Query(default=None),
    status_filter: AppointmentStatus | None = Query(default=None, alias="status"),
    sort: Literal["scheduled_at", "created_at", "last_activity_at"] = Query(default="scheduled_at"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("appointments.read")),
) -> list[AppointmentOut]:
    rows = await list_appointments(
        db,
        from_dt=from_dt,
        to_dt=to_dt,
        assigned_to=assigned_to,
        status_filter=status_filter,
        sort=sort,
        order=order,
    )
    return [AppointmentOut.model_validate(r) for r in rows]


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment_endpoint(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.write")),
) -> AppointmentOut:
    appt = await create_appointment(
        db, org_id=user.org_id, current_user_id=user.legacy_uuid, payload=payload
    )
    return AppointmentOut.model_validate(appt)


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment_endpoint(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("appointments.read")),
) -> AppointmentOut:
    appt = await get_appointment(db, appointment_id)
    if appt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="appointment not found",
        )
    return AppointmentOut.model_validate(appt)


@router.patch("/{appointment_id}", response_model=AppointmentOut)
async def update_appointment_endpoint(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.write")),
) -> AppointmentOut:
    appt = await update_appointment(
        db,
        appointment_id=appointment_id,
        current_user_id=user.legacy_uuid,
        payload=payload,
    )
    return AppointmentOut.model_validate(appt)


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment_endpoint(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("appointments.write")),
) -> Response:
    await delete_appointment(db, appointment_id=appointment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Reschedule / reassign / bulk-action endpoints --------------------------


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule_appointment_endpoint(
    appointment_id: uuid.UUID,
    payload: AppointmentReschedule,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.write")),
) -> AppointmentOut:
    appt = await reschedule_appointment(
        db,
        appointment_id=appointment_id,
        org_id=user.org_id,
        scheduled_at=payload.scheduled_at,
        reason=payload.reason,
        actor_user_id=user.legacy_uuid,
    )
    return AppointmentOut.model_validate(appt)


@router.post("/{appointment_id}/reassign", response_model=AppointmentOut)
async def reassign_appointment_endpoint(
    appointment_id: uuid.UUID,
    payload: AppointmentReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.reassign")),
) -> AppointmentOut:
    appt = await reassign_appointment(
        db,
        appointment_id=appointment_id,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return AppointmentOut.model_validate(appt)


@router.post("/bulk-reassign", response_model=AppointmentBulkReassignResult)
async def bulk_reassign_appointments_endpoint(
    payload: AppointmentBulkReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.reassign")),
) -> AppointmentBulkReassignResult:
    n = await bulk_reassign_appointments(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return AppointmentBulkReassignResult(reassigned=n)


@router.post("/bulk-cancel", response_model=AppointmentBulkCancelResult)
async def bulk_cancel_appointments_endpoint(
    payload: AppointmentBulkCancel,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.write")),
) -> AppointmentBulkCancelResult:
    cancelled, skipped, skipped_by_status = await bulk_cancel_appointments(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        reason=payload.reason,
        actor_user_id=user.legacy_uuid,
    )
    return AppointmentBulkCancelResult(
        cancelled=cancelled, skipped=skipped, skipped_by_status=skipped_by_status
    )


@router.post("/bulk-delete", response_model=AppointmentBulkDeleteResult)
async def bulk_delete_appointments_endpoint(
    payload: AppointmentBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("appointments.write")),
) -> AppointmentBulkDeleteResult:
    """Hard-delete every selected appointment regardless of status.
    Mirrors the single-row `DELETE /{id}` per row — audit + calendar
    sync fire per deleted appointment. Ids not in the caller's org
    are silently dropped by the org-scoped hydrate."""
    n = await bulk_delete_appointments(
        db,
        ids=payload.ids,
        org_id=user.org_id,
    )
    return AppointmentBulkDeleteResult(deleted=n)
