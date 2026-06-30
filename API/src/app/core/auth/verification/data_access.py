"""Data-access layer for the email-verification flow."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserInfo, UserLogin


async def get_user_id_and_email_by_handle(
    session: AsyncSession, user_handle: str
) -> tuple[int, str | None] | None:
    """Resolve a `tbl_user_login.user_id` handle to `(member_id, email)`.

    Used by the click-the-link email-verification flow to look up the
    user the token was issued for. Returns None when the handle is
    unknown.
    """
    row = (
        await session.execute(
            select(UserLogin.id, UserInfo.email)
            .join(UserInfo, UserInfo.member_id == UserLogin.id)
            .where(UserLogin.user_id == user_handle)
        )
    ).first()
    if row is None:
        return None
    return int(row.id), row.email


async def mark_email_verified(session: AsyncSession, *, member_id: int) -> None:
    """Flip `tbl_user_info.is_email_verified=True` for one user."""
    await session.execute(
        update(UserInfo).where(UserInfo.member_id == member_id).values(is_email_verified=True)
    )


__all__ = ["get_user_id_and_email_by_handle", "mark_email_verified"]
