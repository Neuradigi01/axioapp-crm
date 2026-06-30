from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.password import data_access
from src.app.shared.security.password import hash_password
from src.models.password_change_history import PasswordChangeHistory
from src.models.password_reset import PasswordResetToken
from src.providers import email_provider

RESET_TOKEN_TTL = timedelta(hours=1)


async def request_reset(db: AsyncSession, identifier: str) -> None:
    """Issue a reset email if the identifier resolves to an active user.

    Silent on unknown / disabled accounts so a caller cannot probe which
    emails are registered. Only the User pool is handled here; the
    Admin reset flow remains on the legacy `/api/auth/forgot-password`
    endpoint until that surface is retired.
    """
    row = await data_access.find_active_user_by_identifier(db, identifier)
    if row is None:
        return
    member_id, email = row
    if not email:
        return

    token = secrets.token_urlsafe(64)
    data_access.add_password_reset_token(
        db,
        PasswordResetToken(
            member_id=member_id,
            user_type="User",
            token=token,
            expires_at=datetime.now(UTC) + RESET_TOKEN_TTL,
        ),
    )
    await db.commit()
    await email_provider.send_password_reset_email(email, token)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> bool:
    """Consume a reset token and update the user's password.

    Returns False on missing/used/expired token or unknown user. On
    success, the token is marked used and every other outstanding User
    reset token for the same member is invalidated.
    """
    reset_token = await data_access.get_active_reset_token_for_user(db, token)
    if reset_token is None:
        return False

    user = await data_access.get_user_login_by_id(db, reset_token.member_id)
    if user is None:
        return False

    new_hash = hash_password(new_password)
    data_access.add_password_change_history(
        db,
        PasswordChangeHistory(
            member_id=user.id,
            user_type="User",
            old_password_hash=user.password,
            new_password_hash=new_hash,
            change_type="reset",
            changed_by_id=user.id,
        ),
    )
    user.password = new_hash
    reset_token.is_used = True

    await data_access.invalidate_outstanding_reset_tokens(db, member_id=user.id)
    await db.commit()
    return True
