"""Data-access layer for the staff_portal module.

Pure query helpers — no transactions, no audit, no PIN/JWT logic.
Leaf module; never imports a ``service.py``.

Operations:

  * Pickable staff list (cross-module read against ``tbl_user_login``
    ⋈ ``tbl_user_info`` ⋈ ``tbl_organization_members`` ⋈
    ``tbl_staff_profiles``)
      list_active_staff_for_picker — narrow projection of
        ``(legacy_uuid, first_name, last_name)`` so the public login
        picker can render names without leaking PII
  * Member lookup for login validation
      get_active_member_user_for_org — verifies the user belongs to
        the org via ``tbl_organization_members`` and is active
  * Staff profile read (cross-module)
      get_staff_profile_by_user_id — caller (service) checks the
        ``employment_status`` before considering the login valid
  * Session insert
      insert_staff_session
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.staff.models import EmploymentStatus, StaffProfile
from src.app.core.staff_portal.models import StaffSession
from src.app.core.users.models import OrganizationMember, User, UserInfo


async def list_active_staff_for_picker(session: AsyncSession, *, org_id: uuid.UUID) -> list[Row]:
    """Active staff for the login picker. Joins:

      User ⋈ UserInfo ⋈ OrganizationMember ⋈ StaffProfile

    Requires the user + their org membership to be active AND the
    staff profile to be in ``EmploymentStatus.active``. Returns
    ``(legacy_uuid, first_name, last_name)`` rows ordered by first
    name."""
    stmt = (
        select(
            User.legacy_uuid.label("legacy_uuid"),
            UserInfo.first_name,
            UserInfo.last_name,
        )
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .join(StaffProfile, StaffProfile.user_id == User.legacy_uuid)
        .where(OrganizationMember.organization_id == org_id)
        .where(OrganizationMember.is_active.is_(True))
        .where(User.is_active.is_(True))
        .where(StaffProfile.employment_status == EmploymentStatus.active)
        .order_by(UserInfo.first_name.asc())
    )
    return list((await session.execute(stmt)).all())


async def get_active_member_user_for_org(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
) -> User | None:
    """Verify the user belongs to ``org_id`` via an active
    ``tbl_organization_members`` row. Returns the User if so,
    ``None`` otherwise (service surfaces 401 either way to avoid
    enumerating)."""
    return (
        await session.execute(
            select(User)
            .join(
                OrganizationMember,
                OrganizationMember.user_member_id == User.id,
            )
            .where(User.legacy_uuid == user_id)
            .where(OrganizationMember.organization_id == org_id)
            .where(OrganizationMember.is_active.is_(True))
        )
    ).scalar_one_or_none()


async def get_staff_profile_by_user_id(
    session: AsyncSession, user_id: uuid.UUID
) -> StaffProfile | None:
    """Single-row staff profile read keyed by ``user_id``. Service
    inspects ``employment_status`` to decide whether the login is
    valid."""
    return (
        await session.execute(select(StaffProfile).where(StaffProfile.user_id == user_id))
    ).scalar_one_or_none()


def insert_staff_session(session: AsyncSession, staff_session: StaffSession) -> None:
    """Register an already-constructed StaffSession for INSERT."""
    session.add(staff_session)


__all__ = [
    "get_active_member_user_for_org",
    "get_staff_profile_by_user_id",
    "insert_staff_session",
    "list_active_staff_for_picker",
]
