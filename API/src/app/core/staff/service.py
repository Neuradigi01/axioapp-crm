"""Service layer for the staff module.

Five concerns:

1. `list_staff` — joins `users` left-outer with `staff_profiles` so
   every active user shows up even if HR hasn't filled their profile
   yet. Tenant scoping is automatic via the ORM filter.
2. `upsert_profile` — `PUT /staff/{id}` semantics. Replaces the
   profile row if one exists, otherwise inserts.
3. `performance` — composes a `PerformanceOut` from leads (won count,
   active count) and the user's profile. Sales is `Decimal('0')`
   today (placeholder until invoices ship in Phase 5); the spec
   explicitly calls this out.
4. `clock_in` / `clock_out` — enforces "at most one open session per
   user" with a service-level query. Open session = `clock_out_at IS
   NULL`. A second clock-in while one is open returns 409.
5. `attendance_for_user` and `activities_for_user` — windowed reads
   the admin view and the staff portal share.

Audit events fire on every mutation so HR has an unambiguous record.
"""
from __future__ import annotations

import uuid
from datetime import date as Date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import Activity
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.staff.models import (
    Attendance,
    EmploymentStatus,
    StaffProfile,
)
from src.app.core.staff.schemas import (
    ClockInPayload,
    ClockOutPayload,
    StaffListItem,
    StaffProfileUpsert,
)
from src.app.core.users.models import User


def _profile_snapshot(p: StaffProfile) -> dict[str, Any]:
    return {
        "user_id": str(p.user_id),
        "commission_rate": str(p.commission_rate),
        "monthly_target": str(p.monthly_target),
        "rating": str(p.rating),
        "employment_status": p.employment_status.value,
        "joined_at": p.joined_at.isoformat(),
    }


def _attendance_snapshot(a: Attendance) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "user_id": str(a.user_id),
        "clock_in_at": a.clock_in_at.isoformat(),
        "clock_out_at": (
            a.clock_out_at.isoformat() if a.clock_out_at is not None else None
        ),
        "date": a.date.isoformat(),
        "notes": a.notes,
    }


async def _ensure_user_in_scope(
    session: AsyncSession, user_id: uuid.UUID
) -> User:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user {user_id} not found in this org",
        )
    return user


# --- staff list (users left-outer staff_profiles) ---


async def list_staff(session: AsyncSession) -> list[StaffListItem]:
    """Every user in the org + their profile (if any)."""
    stmt = (
        select(User, StaffProfile)
        .outerjoin(StaffProfile, StaffProfile.user_id == User.id)
        .order_by(User.full_name.asc())
    )
    rows = (await session.execute(stmt)).all()
    out: list[StaffListItem] = []
    for user, profile in rows:
        out.append(
            StaffListItem(
                id=user.id,
                org_id=user.org_id,
                email=user.email,
                full_name=user.full_name,
                phone=user.phone,
                role_id=user.role_id,
                is_active=user.is_active,
                commission_rate=(
                    profile.commission_rate if profile is not None else None
                ),
                monthly_target=(
                    profile.monthly_target if profile is not None else None
                ),
                rating=profile.rating if profile is not None else None,
                employment_status=(
                    profile.employment_status if profile is not None else None
                ),
                joined_at=profile.joined_at if profile is not None else None,
            )
        )
    return out


# --- profile upsert ---


async def get_profile(
    session: AsyncSession, user_id: uuid.UUID
) -> Optional[StaffProfile]:
    return (
        await session.execute(
            select(StaffProfile).where(StaffProfile.user_id == user_id)
        )
    ).scalar_one_or_none()


async def upsert_profile(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: StaffProfileUpsert,
) -> StaffProfile:
    await _ensure_user_in_scope(session, user_id)

    existing = await get_profile(session, user_id)
    before = _profile_snapshot(existing) if existing is not None else None

    if existing is None:
        profile = StaffProfile(
            org_id=org_id,
            user_id=user_id,
            commission_rate=payload.commission_rate,
            monthly_target=payload.monthly_target,
            rating=payload.rating,
            employment_status=payload.employment_status,
            joined_at=payload.joined_at or Date.today(),
        )
        session.add(profile)
    else:
        existing.commission_rate = payload.commission_rate
        existing.monthly_target = payload.monthly_target
        existing.rating = payload.rating
        existing.employment_status = payload.employment_status
        if payload.joined_at is not None:
            existing.joined_at = payload.joined_at
        profile = existing

    await session.commit()
    await session.refresh(profile)

    await audit.log(
        "staff.profile_updated" if before is not None else "staff.profile_created",
        entity_type="staff_profile",
        entity_id=profile.user_id,
        before=before,
        after=_profile_snapshot(profile),
    )
    return profile


# --- performance ---


async def compute_performance(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, Any]:
    await _ensure_user_in_scope(session, user_id)

    leads_won = (
        await session.execute(
            select(func.count())
            .select_from(Lead)
            .where(Lead.assigned_to_id == user_id)
            .where(Lead.status == LeadStatus.won)
        )
    ).scalar_one()
    leads_active = (
        await session.execute(
            select(func.count())
            .select_from(Lead)
            .where(Lead.assigned_to_id == user_id)
            .where(Lead.status == LeadStatus.active)
        )
    ).scalar_one()

    profile = await get_profile(session, user_id)
    monthly_target = profile.monthly_target if profile is not None else Decimal("0")
    rating = profile.rating if profile is not None else Decimal("0")
    commission_rate = (
        profile.commission_rate if profile is not None else Decimal("0")
    )

    # `sales` is a Phase 5 invoices number — placeholder zero today.
    sales = Decimal("0")
    target_progress_pct: Optional[float] = None
    if monthly_target > 0:
        target_progress_pct = float(sales / monthly_target * 100)

    return {
        "user_id": user_id,
        "leads_converted": int(leads_won),
        "leads_active": int(leads_active),
        "sales": sales,
        "monthly_target": monthly_target,
        "target_progress_pct": target_progress_pct,
        "rating": rating,
        "commission_rate": commission_rate,
    }


# --- attendance ---


async def list_attendance(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    from_dt: Optional[Date] = None,
    to_dt: Optional[Date] = None,
) -> list[Attendance]:
    filters: list[Any] = [Attendance.user_id == user_id]
    if from_dt is not None:
        filters.append(Attendance.date >= from_dt)
    if to_dt is not None:
        filters.append(Attendance.date <= to_dt)
    stmt = (
        select(Attendance)
        .where(and_(*filters))
        .order_by(Attendance.clock_in_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_activities_for(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 100
) -> list[Activity]:
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _current_open_session(
    session: AsyncSession, user_id: uuid.UUID
) -> Optional[Attendance]:
    """The user's currently-open attendance row, if any."""
    return (
        await session.execute(
            select(Attendance)
            .where(Attendance.user_id == user_id)
            .where(Attendance.clock_out_at.is_(None))
        )
    ).scalar_one_or_none()


async def clock_in(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ClockInPayload,
) -> Attendance:
    await _ensure_user_in_scope(session, user_id)

    if (await _current_open_session(session, user_id)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user already has an open attendance session — clock out first",
        )

    now = datetime.now(timezone.utc)
    attendance = Attendance(
        org_id=org_id,
        user_id=user_id,
        clock_in_at=now,
        date=now.date(),
        notes=payload.notes,
    )
    session.add(attendance)
    await session.commit()
    await session.refresh(attendance)

    await audit.log(
        "staff.clocked_in",
        entity_type="attendance",
        entity_id=attendance.id,
        after=_attendance_snapshot(attendance),
    )
    return attendance


async def clock_out(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    payload: ClockOutPayload,
) -> Attendance:
    await _ensure_user_in_scope(session, user_id)

    open_session = await _current_open_session(session, user_id)
    if open_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no open attendance session to clock out",
        )

    before = _attendance_snapshot(open_session)
    open_session.clock_out_at = datetime.now(timezone.utc)
    if payload.notes is not None:
        existing = open_session.notes
        open_session.notes = (
            f"{existing}\n{payload.notes}" if existing else payload.notes
        )
    await session.commit()
    await session.refresh(open_session)

    await audit.log(
        "staff.clocked_out",
        entity_type="attendance",
        entity_id=open_session.id,
        before=before,
        after=_attendance_snapshot(open_session),
    )
    return open_session


__all__ = [
    "EmploymentStatus",
    "clock_in",
    "clock_out",
    "compute_performance",
    "get_profile",
    "list_activities_for",
    "list_attendance",
    "list_staff",
    "upsert_profile",
]
