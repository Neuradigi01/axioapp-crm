"""HTTP routes for the appointments module.

  GET    /api/v1/appointments?from=&to=&assigned_to=&status=  → flat array (calendar)
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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import AppointmentStatus
from src.app.core.appointments.schemas import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
)
from src.app.core.appointments.service import (
    create_appointment,
    delete_appointment,
    get_appointment,
    list_appointments,
    update_appointment,
)
from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.get("", response_model=list[AppointmentOut])
async def list_appointments_endpoint(
    from_dt: Optional[datetime] = Query(default=None, alias="from"),
    to_dt: Optional[datetime] = Query(default=None, alias="to"),
    assigned_to: Optional[uuid.UUID] = Query(default=None),
    status_filter: Optional[AppointmentStatus] = Query(
        default=None, alias="status"
    ),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("appointments.read")),
) -> list[AppointmentOut]:
    rows = await list_appointments(
        db,
        from_dt=from_dt,
        to_dt=to_dt,
        assigned_to=assigned_to,
        status_filter=status_filter,
    )
    return [AppointmentOut.model_validate(r) for r in rows]


@router.post(
    "", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED
)
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
