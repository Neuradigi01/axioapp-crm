from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.app.shared.security.password import hash_password
from src.models.password_change_history import PasswordChangeHistory
from src.models.password_reset import PasswordResetToken
from src.models.user import UserInfo, UserLogin
from src.providers import email_provider

RESET_TOKEN_TTL = timedelta(hours=1)


async def request_reset(db: AsyncSession, identifier: str) -> None:
    """Issue a reset email if the identifier resolves to an active user.

    Silent on unknown / disabled accounts so a caller cannot probe which
    emails are registered. Only the User pool is handled here; the
    Admin reset flow remains on the legacy `/api/auth/forgot-password`
    endpoint until that surface is retired.
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
    row = (await db.execute(stmt)).first()
    if row is None or not row.email:
        return

    token = secrets.token_urlsafe(64)
    db.add(
        PasswordResetToken(
            member_id=row.id,
            user_type="User",
            token=token,
            expires_at=datetime.now(timezone.utc) + RESET_TOKEN_TTL,
        )
    )
    await db.commit()
    await email_provider.send_password_reset_email(row.email, token)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> bool:
    """Consume a reset token and update the user's password.

    Returns False on missing/used/expired token or unknown user. On
    success, the token is marked used and every other outstanding User
    reset token for the same member is invalidated.
    """
    reset_token = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used.is_(False),
                PasswordResetToken.expires_at > func.now(),
                PasswordResetToken.user_type == "User",
            )
        )
    ).scalar_one_or_none()
    if reset_token is None:
        return False

    user = (
        await db.execute(
            select(UserLogin).where(UserLogin.id == reset_token.member_id)
        )
    ).scalar_one_or_none()
    if user is None:
        return False

    new_hash = hash_password(new_password)
    db.add(
        PasswordChangeHistory(
            member_id=user.id,
            user_type="User",
            old_password_hash=user.password,
            new_password_hash=new_hash,
            change_type="reset",
            changed_by_id=user.id,
        )
    )
    user.password = new_hash
    reset_token.is_used = True

    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.member_id == user.id,
            PasswordResetToken.user_type == "User",
            PasswordResetToken.is_used.is_(False),
        )
        .values(is_used=True)
    )
    await db.commit()
    return True
