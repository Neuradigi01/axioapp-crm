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
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Lookup by email. `email` is stored as CITEXT so this is case-insensitive."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_users(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[User]:
    result = await session.execute(
        select(User).order_by(func.lower(User.email)).limit(limit).offset(offset)
    )
    return list(result.scalars().all())
