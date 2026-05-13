"""HTTP routes for the staff-portal auth surface.

Unauthenticated:
  GET  /api/v1/staff-portal/users?org_slug=demo   → picker rows
  POST /api/v1/staff-portal/auth/login            → {staff_token, expires_at}

Authenticated as `scope="staff"`:
  GET  /api/v1/staff-portal/me                    → who-am-i
  GET  /api/v1/staff-portal/me/performance        → reuse compute_performance
  GET  /api/v1/staff-portal/me/attendance         → list_attendance
  GET  /api/v1/staff-portal/me/activity           → list_activities_for
  POST /api/v1/staff-portal/me/clock-in           → svc.clock_in
  POST /api/v1/staff-portal/me/clock-out          → svc.clock_out

The `/me/*` set deliberately reuses the same service functions from
`core.staff.service` — the only difference is the auth surface
(`get_current_staff` vs `require_permissions(...)`) and the implicit
"the user is themselves" identity.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_staff
from src.app.core.staff.schemas import (
    AttendanceOut,
    ClockInPayload,
    ClockOutPayload,
    PerformanceOut,
)
from src.app.core.staff.service import (
    clock_in as svc_clock_in,
    clock_out as svc_clock_out,
    compute_performance,
    list_activities_for,
    list_attendance,
)
from src.app.core.activities.schemas import ActivityOut
from src.app.core.staff_portal.schemas import (
    StaffLoginPayload,
    StaffLoginResponse,
    StaffMeOut,
    StaffPickerUser,
)
from src.app.core.staff_portal.service import list_pickable_users, login
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/staff-portal", tags=["StaffPortal"])


@router.get("/users", response_model=list[StaffPickerUser])
async def list_pickable_users_endpoint(
    org_slug: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> list[StaffPickerUser]:
    return await list_pickable_users(db, org_slug=org_slug)


@router.post(
    "/auth/login",
    response_model=StaffLoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login_endpoint(
    payload: StaffLoginPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StaffLoginResponse:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    result = await login(
        db,
        org_slug=payload.org_slug,
        user_id=payload.user_id,
        pin=payload.pin,
        ip=ip,
        ua=ua,
    )
    return StaffLoginResponse.model_validate(result)


# --- authenticated `me` surface (scope="staff") ---


@router.get("/me", response_model=StaffMeOut)
async def me_endpoint(
    user: User = Depends(get_current_staff),
) -> StaffMeOut:
    return StaffMeOut(
        id=user.id, org_id=user.org_id, full_name=user.full_name, email=user.email
    )


@router.get("/me/performance", response_model=PerformanceOut)
async def me_performance_endpoint(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> PerformanceOut:
    data = await compute_performance(db, user.id)
    return PerformanceOut(**data)


@router.get("/me/attendance", response_model=list[AttendanceOut])
async def me_attendance_endpoint(
    from_: Optional[Date] = Query(default=None, alias="from"),
    to: Optional[Date] = Query(default=None),
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> list[AttendanceOut]:
    rows = await list_attendance(
        db, user_id=user.id, from_dt=from_, to_dt=to
    )
    return [AttendanceOut.model_validate(r) for r in rows]


@router.get("/me/activity", response_model=list[ActivityOut])
async def me_activity_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityOut]:
    rows = await list_activities_for(db, user.id, limit=limit)
    return [ActivityOut.model_validate(r) for r in rows]


@router.post(
    "/me/clock-in", response_model=AttendanceOut, status_code=201
)
async def me_clock_in_endpoint(
    payload: ClockInPayload,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    row = await svc_clock_in(
        db, org_id=user.org_id, user_id=user.id, payload=payload
    )
    return AttendanceOut.model_validate(row)


@router.post("/me/clock-out", response_model=AttendanceOut)
async def me_clock_out_endpoint(
    payload: ClockOutPayload,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    row = await svc_clock_out(db, user_id=user.id, payload=payload)
    return AttendanceOut.model_validate(row)
