from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, SMS_ENABLED
from src.constants import messages
from src.core.security.password import hash_password, verify_password
from src.data_access import admin_da, password_change_history_da, user_da
from src.providers import otp_provider, two_factor_provider
from src.schemas.common import ChangePasswordRequest

# ── Shared record resolution ────────────────────────────────────────


async def get_member_with_contact_info(db: AsyncSession, user_id: str, user_type: str):
    """Fetch user/admin record with email and mobile.
    Returns (record, email, mobile) or (None, None, None)."""
    if user_type == "User":
        user = await user_da.get_user_with_info(db, user_id)
        if not user:
            return None, None, None
        email = user.user_info.email if user.user_info else None
        mobile = user.user_info.mobile_no if user.user_info else None
        return user, email, mobile
    else:
        admin = await admin_da.get_by_user_id(db, user_id)
        if not admin:
            return None, None, None
        return admin, admin.email, admin.mobile_no


# ── Shared 2FA helpers ───────────────────────────────────────────────


async def _send_otp_by_method(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    email: str | None,
    mobile: str | None,
    method: str,
    purpose: str,
) -> dict | None:
    """Send OTP via the specified method.
    Returns error dict on failure, None on success.
    Caller must commit the db session after a successful call."""
    if method == "email":
        if not EMAIL_ENABLED or not email:
            return {"success": False, "message": messages.EMAIL_NOT_AVAILABLE}
        await otp_provider.send_otp_email(db, member_id, user_type, email, purpose)
    elif method == "sms":
        if not SMS_ENABLED or not mobile:
            return {"success": False, "message": messages.SMS_NOT_AVAILABLE}
        await otp_provider.send_otp_sms(db, member_id, user_type, mobile, purpose)
    else:
        return {"success": False, "message": messages.AUTHENTICATOR_NO_OTP}
    return None


async def send_otp_to_member(
    db: AsyncSession,
    user_id: str,
    user_type: str,
    method: str,
    purpose: str,
    *,
    require_2fa_enabled: bool = False,
) -> dict:
    """Lookup member, send OTP, commit. Used by 2FA setup and action verification."""
    record, email, mobile = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if require_2fa_enabled and not record.two_factor_enabled:
        return {"success": False, "message": messages.TWO_FACTOR_NOT_ENABLED}

    error = await _send_otp_by_method(db, record.id, user_type, email, mobile, method, purpose)
    if error:
        return error

    await db.commit()
    return {"success": True, "message": messages.VERIFICATION_CODE_SENT}


async def verify_2fa_code(
    db: AsyncSession,
    member_id: int,
    record,
    method: str,
    code: str,
    purpose: str,
) -> bool:
    """Verify a 2FA code using the appropriate method (authenticator, email, or sms)."""
    if method == "authenticator":
        if not record.two_factor_secret:
            return False
        return two_factor_provider.verify_totp_code(record.two_factor_secret, code)
    elif method in ("email", "sms"):
        return await otp_provider.verify_otp(db, member_id, code, purpose)
    return False


# ── Change password ──────────────────────────────────────────────────


async def change_password(
    db: AsyncSession, user_id: str, user_type: str, req: ChangePasswordRequest
) -> dict:
    if user_type == "User":
        record = await user_da.get_by_user_id(db, user_id)
    else:
        record = await admin_da.get_by_user_id(db, user_id)

    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if not verify_password(req.old_password, record.password):
        return {"success": False, "message": messages.OLD_PASSWORD_INCORRECT}

    hashed = hash_password(req.new_password)

    await password_change_history_da.insert_history(
        db,
        record.id,
        user_type,
        old_password_hash=record.password,
        new_password_hash=hashed,
        change_type="self_change",
        changed_by_id=record.id,
    )

    if user_type == "User":
        await user_da.update_password(db, user_id, hashed)
    else:
        await admin_da.update_password(db, user_id, hashed)
    await db.commit()

    return {"success": True, "message": messages.PASSWORD_CHANGED}
