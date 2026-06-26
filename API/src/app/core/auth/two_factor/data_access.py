"""Data-access layer for the 2FA login challenge."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserLogin


async def get_two_factor_columns(
    session: AsyncSession, *, member_id: int
) -> tuple[bool, str | None, str | None] | None:
    """Read `(enabled, method, secret)` from `tbl_user_login` for a user.

    Returns None when the user row is missing. The layered `User`
    mapper hides these columns, so this goes through the legacy
    `UserLogin` mapper.
    """
    row = (
        await session.execute(
            select(
                UserLogin.two_factor_enabled,
                UserLogin.two_factor_method,
                UserLogin.two_factor_secret,
            ).where(UserLogin.id == member_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return bool(row[0]), row[1], row[2]


__all__ = ["get_two_factor_columns"]
