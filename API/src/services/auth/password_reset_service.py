import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.security.password import hash_password
from src.models.password_reset import PasswordResetToken
from src.data_access import user_da, admin_da, password_reset_da, password_change_history_da
from src.providers import email_provider
from src.services.auth.resolver_service import resolve_user, resolve_admin
from src.constants import messages


async def request_password_reset(db: AsyncSession, identifier: str) -> dict:
    safe_msg = messages.PASSWORD_RESET_LINK_SENT
    token_str = secrets.token_urlsafe(64)

    # Try to find user by user_id or email
    user = await resolve_user(db, identifier)
    if user:
        email = user.user_info.email if user.user_info else None
        if not email:
            return {"success": True, "message": safe_msg}
        reset_token = PasswordResetToken(
            member_id=user.id,
            user_type="User",
            token=token_str,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(reset_token)
        await db.commit()
        await email_provider.send_password_reset_email(email, token_str)
        return {"success": True, "message": safe_msg}

    # Try admin
    admin = await resolve_admin(db, identifier)
    if admin and admin.email:
        reset_token = PasswordResetToken(
            member_id=admin.id,
            user_type="Admin",
            token=token_str,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(reset_token)
        await db.commit()
        await email_provider.send_password_reset_email(admin.email, token_str)
        return {"success": True, "message": safe_msg}

    # Not found — still return success to prevent enumeration
    return {"success": True, "message": safe_msg}


async def reset_password(db: AsyncSession, token: str, new_password: str) -> dict:
    reset_token = await password_reset_da.get_valid_token(db, token)
    if not reset_token:
        return {"success": False, "message": messages.INVALID_RESET_TOKEN}

    hashed = hash_password(new_password)

    if reset_token.user_type == "User":
        record = await user_da.get_user_by_member_id(db, reset_token.member_id)
    else:
        record = await admin_da.get_by_id(db, reset_token.member_id)

    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    # Resolve text user_id for password update (which uses text user_id lookup)
    text_user_id = record.user_id if reset_token.user_type == "User" else record.admin_user_id

    await password_change_history_da.insert_history(
        db, reset_token.member_id, reset_token.user_type,
        old_password_hash=record.password,
        new_password_hash=hashed,
        change_type="reset",
        changed_by_id=reset_token.member_id,
    )

    if reset_token.user_type == "User":
        await user_da.update_password(db, text_user_id, hashed)
    else:
        await admin_da.update_password(db, text_user_id, hashed)

    reset_token.is_used = True
    await password_reset_da.invalidate_user_tokens(db, reset_token.member_id, reset_token.user_type)
    await db.commit()

    return {"success": True, "message": messages.PASSWORD_CHANGED}
