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

from src.app.core.users.models import User


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
    """Lookup by email. `email` is stored as CITEXT so this is case-insensitive."""
    # `email IS NOT NULL` excludes the legacy `tbl_user_login` admin row.
    result = await session.execute(
        select(User).where(User.email == email, User.email.is_not(None))
    )
    return result.scalar_one_or_none()


async def list_users(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[User]:
    # `email IS NOT NULL` excludes the legacy `tbl_user_login` admin row
    # — which has NULL email/org_id and would otherwise leak into admin
    # listings if the tenant filter is bypassed somehow.
    result = await session.execute(
        select(User)
        .where(User.email.is_not(None))
        .order_by(func.lower(User.email))
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
