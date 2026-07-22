"""HTTP routes for the staff module.

  GET    /api/v1/staff
  PUT    /api/v1/staff/{user_id}
  GET    /api/v1/staff/{user_id}/performance
  GET    /api/v1/staff/{user_id}/attendance?from=&to=
  GET    /api/v1/staff/{user_id}/activity?limit=
  POST   /api/v1/staff/{user_id}/clock-in
  POST   /api/v1/staff/{user_id}/clock-out

Reads need `staff.read`; profile writes need `staff.write`; clock
in/out needs `attendance.write`. Tenant scoping is automatic via the
ORM filter on `TenantScoped`.
"""

from __future__ import annotations

import uuid
from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities.schemas import ActivityOut
from src.app.core.auth.dependencies import require_permissions
from src.app.core.staff.schemas import (
    AttendanceOut,
    ClockInPayload,
    ClockOutPayload,
    PerformanceOut,
    StaffListItem,
    StaffProfileOut,
    StaffProfileUpsert,
)
from src.app.core.staff.service import (
    clock_in as svc_clock_in,
)
from src.app.core.staff.service import (
    clock_out as svc_clock_out,
)
from src.app.core.staff.service import (
    compute_performance,
    list_activities_for,
    list_attendance,
    list_staff,
    upsert_profile,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get("", response_model=list[StaffListItem])
async def list_staff_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("staff.read")),
) -> list[StaffListItem]:
    return await list_staff(db, org_id=user.org_id)


@router.get("/present-today", response_model=dict)
async def present_today_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("staff.read")),
) -> dict:
    """Return today's headcount: ``{count: N}`` where ``N`` is the
    number of distinct users who have at least one attendance row
    dated today. Consumed by the Staff dashboard "Present today" KPI.
    """
    from src.app.core.staff.service import count_present_today

    n = await count_present_today(db, org_id=user.org_id)
    return {"count": n}


@router.get("/revenue-totals", response_model=dict)
async def revenue_totals_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("staff.read")),
) -> dict:
    """Return ``{total, today}`` — sums of ``Invoice.total`` over paid
    invoices in this org (all-time and today). Consumed by the Staff
    dashboard's Total Revenue + Today's Revenue KPI cards.

    Currency is assumed uniform per org (invoices carry a currency
    column but multi-currency aggregation is future work — orgs are
    single-currency in v1).
    """
    from src.app.core.staff.service import revenue_totals

    total, today = await revenue_totals(db, org_id=user.org_id)
    return {"total": total, "today": today}


@router.put("/{user_id}", response_model=StaffProfileOut)
async def upsert_profile_endpoint(
    user_id: uuid.UUID,
    payload: StaffProfileUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("staff.write")),
) -> StaffProfileOut:
    profile = await upsert_profile(db, org_id=user.org_id, user_id=user_id, payload=payload)
    return StaffProfileOut.model_validate(profile)


@router.get("/{user_id}/performance", response_model=PerformanceOut)
async def performance_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("staff.read")),
) -> PerformanceOut:
    data = await compute_performance(db, user_id)
    return PerformanceOut(**data)


@router.get("/{user_id}/attendance", response_model=list[AttendanceOut])
async def attendance_endpoint(
    user_id: uuid.UUID,
    from_: Date | None = Query(default=None, alias="from"),
    to: Date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("staff.read")),
) -> list[AttendanceOut]:
    rows = await list_attendance(db, user_id=user_id, from_dt=from_, to_dt=to)
    return [AttendanceOut.model_validate(r) for r in rows]


@router.get("/{user_id}/activity", response_model=list[ActivityOut])
async def activity_endpoint(
    user_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("staff.read")),
) -> list[ActivityOut]:
    rows = await list_activities_for(db, user_id, limit=limit)
    return [ActivityOut.model_validate(r) for r in rows]


@router.post(
    "/{user_id}/clock-in",
    response_model=AttendanceOut,
    status_code=201,
)
async def clock_in_endpoint(
    user_id: uuid.UUID,
    payload: ClockInPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("attendance.write")),
) -> AttendanceOut:
    row = await svc_clock_in(db, org_id=user.org_id, user_id=user_id, payload=payload)
    return AttendanceOut.model_validate(row)


@router.post("/{user_id}/clock-out", response_model=AttendanceOut)
async def clock_out_endpoint(
    user_id: uuid.UUID,
    payload: ClockOutPayload,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("attendance.write")),
) -> AttendanceOut:
    row = await svc_clock_out(db, user_id=user_id, payload=payload)
    return AttendanceOut.model_validate(row)
