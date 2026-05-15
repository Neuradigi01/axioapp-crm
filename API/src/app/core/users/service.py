"""Service layer for users.

Reads only — write paths (create/update/deactivate user) land in the
admin UI step. Selects are auto-scoped to the active tenant by the
`do_orm_execute` listener in `src.app.shared.orm`, so callers don't
have to thread `org_id` through.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.users.models import OrganizationMember, User, UserInfo


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Look up a FurnitureCRM user by their UUID identity.

    After DR.6.3 the User model is backed by `tbl_user_login`, whose
    storage PK (`User.id`) is bigint. The UUID that callers carry
    around — JWT `sub`, audit FKs, AuthSession.user_id — lives in
    `User.legacy_uuid`. We query against that column.
    """
    result = await session.execute(
        select(User).where(User.legacy_uuid == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Lookup by email. `email` is stored as CITEXT so this is case-insensitive.

    After DR.7 the email column lives on `tbl_user_info`, so the lookup
    joins through that table. The JOIN naturally excludes the legacy
    `tbl_user_login` admin row (no membership) when an org context is
    needed — callers wanting org isolation should compose with that
    layer themselves; this helper is global by design.
    """
    result = await session.execute(
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .where(UserInfo.email == email)
    )
    return result.scalar_one_or_none()


async def list_users(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[User]:
    """List FurnitureCRM users, optionally scoped to an org membership.

    After DR.7 the email + org_membership live on separate tables, so
    we JOIN through tbl_user_info (for ordering by email) and
    tbl_organization_members (for the org filter + active flag).
    """
    stmt = (
        select(User)
        .join(UserInfo, UserInfo.member_id == User.id)
        .join(
            OrganizationMember,
            OrganizationMember.user_member_id == User.id,
        )
        .where(OrganizationMember.is_active.is_(True))
        .order_by(func.lower(UserInfo.email))
        .limit(limit)
        .offset(offset)
    )
    if org_id is not None:
        stmt = stmt.where(OrganizationMember.organization_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
