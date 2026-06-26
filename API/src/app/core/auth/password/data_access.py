"""Data-access layer for the password-reset flow.

Pure query helpers — no transactions, no audit. Operates on the legacy
`UserLogin` / `UserInfo` mappers (the layered `User` mapper hides
several columns the reset flow needs to touch).
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.models.password_change_history import PasswordChangeHistory
from src.models.password_reset import PasswordResetToken
from src.models.user import UserInfo, UserLogin


async def find_active_user_by_identifier(
    session: AsyncSession, identifier: str
) -> tuple[int, str | None] | None:
    """Look up an active user by either `user_id` handle or email.

    Returns `(member_id, email)` on a hit or None when the identifier
    doesn't resolve. The caller treats a missing email the same way as
    a missing row — silent return, no password-reset email dispatched.
    """
    stmt = (
        select(UserLogin.id, UserInfo.email)
        .outerjoin(UserInfo, UserInfo.member_id == UserLogin.id)
        .where(
            UserLogin.is_active.is_(True),
            (UserLogin.user_id == identifier) | (UserInfo.email == identifier),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return int(row.id), row.email


def add_password_reset_token(
    session: AsyncSession, token: PasswordResetToken
) -> PasswordResetToken:
    """Stage a new `tbl_password_reset_tokens` row in the unit-of-work."""
    session.add(token)
    return token


async def get_active_reset_token_for_user(
    session: AsyncSession, token: str
) -> PasswordResetToken | None:
    """Find an unused, unexpired User-pool reset token by its plaintext value."""
    result = await session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.is_used.is_(False),
            PasswordResetToken.expires_at > func.now(),
            PasswordResetToken.user_type == "User",
        )
    )
    return result.scalar_one_or_none()


async def get_user_login_by_id(
    session: AsyncSession, member_id: int
) -> UserLogin | None:
    """Load the legacy `UserLogin` row by bigint PK."""
    result = await session.execute(
        select(UserLogin).where(UserLogin.id == member_id)
    )
    return result.scalar_one_or_none()


def add_password_change_history(
    session: AsyncSession, row: PasswordChangeHistory
) -> PasswordChangeHistory:
    """Stage a `tbl_password_change_history` row in the unit-of-work."""
    session.add(row)
    return row


async def invalidate_outstanding_reset_tokens(
    session: AsyncSession, *, member_id: int
) -> None:
    """Mark every non-used User-pool reset token for this member as used.

    Defensive cleanup so a recently-completed reset can't be retried via
    a still-valid token issued seconds earlier.
    """
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.member_id == member_id,
            PasswordResetToken.user_type == "User",
            PasswordResetToken.is_used.is_(False),
        )
        .values(is_used=True)
    )


__all__ = [
    "add_password_change_history",
    "add_password_reset_token",
    "find_active_user_by_identifier",
    "get_active_reset_token_for_user",
    "get_user_login_by_id",
    "invalidate_outstanding_reset_tokens",
]
