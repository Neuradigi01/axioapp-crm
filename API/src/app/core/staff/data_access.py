"""Data-access layer for the staff module.

Pure query helpers — no transactions, no audit, no in-scope checks.
Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Staff users + profiles (``tbl_user_login`` ⋈ ``tbl_user_info`` ⋈
    ``tbl_staff_profiles``)
      list_users_with_profiles — the LEFT-OUTER staff list that
        powers Settings → Staff
      get_staff_profile_by_user_id, insert_staff_profile
  * Attendance (``tbl_attendances``)
      find_open_attendance_session, list_attendance_for_user,
      insert_attendance
  * Cross-module reads (kept here because the projections are
    staff-specific)
      count_leads_for_user_by_status — drives the performance card
      list_activities_for_user — drives the staff activity feed
"""
from __future__ import annotations

import uuid
from datetime import date as Date
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.activities.models import Activity
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.staff.models import Attendance, StaffProfile
from src.app.core.users.models import User, UserInfo


# --- Staff users + profiles ---------------------------------------------


async def list_users_with_profiles(
    session: AsyncSession,
) -> list[Row]:
    """Every user in the org joined LEFT-OUTER against
    ``tbl_staff_profiles``. Users without profiles appear with a NULL
    profile — Settings → Staff needs all of them. Ordered by
    ``UserInfo.first_name``."""
    stmt = (
        select(User, StaffProfile)
        .join(UserInfo, UserInfo.member_id == User.id)
        .outerjoin(
            StaffProfile, StaffProfile.user_id == User.legacy_uuid
        )
        .order_by(UserInfo.first_name.asc())
    )
    return list((await session.execute(stmt)).all())


async def get_staff_profile_by_user_id(
    session: AsyncSession, user_id: uuid.UUID
) -> Optional[StaffProfile]:
    """Single-row read of the staff profile keyed by ``user_id`` (the
    UUID identity that joins to ``User.legacy_uuid``)."""
    return (
        await session.execute(
            select(StaffProfile).where(StaffProfile.user_id == user_id)
        )
    ).scalar_one_or_none()


def insert_staff_profile(
    session: AsyncSession, profile: StaffProfile
) -> None:
    """Register an already-constructed StaffProfile for INSERT."""
    session.add(profile)


# --- Attendance ---------------------------------------------------------


async def find_open_attendance_session(
    session: AsyncSession, user_id: uuid.UUID
) -> Optional[Attendance]:
    """The user's currently-open attendance row (``clock_out_at IS
    NULL``), if any. Used by the "at most one open session" guard on
    clock-in."""
    return (
        await session.execute(
            select(Attendance)
            .where(Attendance.user_id == user_id)
            .where(Attendance.clock_out_at.is_(None))
        )
    ).scalar_one_or_none()


async def list_attendance_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    from_dt: Optional[Date] = None,
    to_dt: Optional[Date] = None,
) -> list[Attendance]:
    """Windowed read of one user's attendance rows, newest first.
    ``from_dt`` / ``to_dt`` bound the ``date`` column inclusively."""
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


def insert_attendance(
    session: AsyncSession, attendance: Attendance
) -> None:
    """Register an already-constructed Attendance for INSERT."""
    session.add(attendance)


# --- Cross-module reads (staff-specific projections) --------------------


async def count_leads_for_user_by_status(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    status_filter: LeadStatus,
) -> int:
    """Count leads assigned to ``user_id`` whose ``status`` matches.
    Drives the performance card's "leads won" / "leads active"
    numbers."""
    result = await session.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.assigned_to_id == user_id)
        .where(Lead.status == status_filter)
    )
    return int(result.scalar_one() or 0)


async def list_activities_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 100,
) -> list[Activity]:
    """Latest ``limit`` activities authored by ``user_id``, newest
    first. Used by the staff activity feed (both admin view + staff
    portal)."""
    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .order_by(Activity.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "count_leads_for_user_by_status",
    "find_open_attendance_session",
    "get_staff_profile_by_user_id",
    "insert_attendance",
    "insert_staff_profile",
    "list_activities_for_user",
    "list_attendance_for_user",
    "list_users_with_profiles",
]
