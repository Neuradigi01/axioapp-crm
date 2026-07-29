from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, SMS_ENABLED
from src.constants import messages
from src.data_access import admin_da, user_da
from src.providers import two_factor_provider
from src.services.common_service import get_member_with_contact_info, verify_2fa_code
from src.utilities.formatting import mask_email, mask_mobile


async def _update_2fa(db, user_id, user_type, *, enabled, method, secret=None):
    if user_type == "User":
        await user_da.update_two_factor(
            db,
            user_id,
            two_factor_enabled=enabled,
            two_factor_method=method,
            two_factor_secret=secret,
        )
    else:
        await admin_da.update_two_factor(
            db,
            user_id,
            two_factor_enabled=enabled,
            two_factor_method=method,
            two_factor_secret=secret,
        )


async def _clear_2fa(db, user_id, user_type):
    if user_type == "User":
        await user_da.clear_two_factor(db, user_id)
    else:
        await admin_da.clear_two_factor(db, user_id)


async def get_2fa_status(db: AsyncSession, user_id: str, user_type: str) -> dict:
    record, email, mobile = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "two_factor_enabled": record.two_factor_enabled,
            "two_factor_method": record.two_factor_method,
            "masked_email": mask_email(email) if email else None,
            "masked_mobile": mask_mobile(mobile) if mobile else None,
            "email_enabled": EMAIL_ENABLED,
            "sms_enabled": SMS_ENABLED,
        },
    }


async def setup_2fa_authenticator(db: AsyncSession, user_id: str, user_type: str) -> dict:
    record, _, _ = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    # Generate plaintext once for the QR (the QR IS the secret in a
    # QR-shaped envelope). Persist only the Fernet-encrypted form.
    plaintext_secret = two_factor_provider.generate_totp_secret()
    qr_code = two_factor_provider.generate_qr_code(plaintext_secret, user_id)
    encrypted_secret = two_factor_provider.encrypt_totp_secret(plaintext_secret)

    if user_type == "User":
        await user_da.set_two_factor_secret(db, user_id, encrypted_secret)
    else:
        await admin_da.set_two_factor_secret(db, user_id, encrypted_secret)
    await db.commit()

    # Don't return the raw seed alongside the QR — the QR encodes it,
    # and clients don't need a second copy. Cuts one extra JSON field
    # of exposure surface (server logs, browser history, etc.).
    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "qr_code": qr_code,
        },
    }


async def verify_and_enable_2fa(
    db: AsyncSession,
    user_id: str,
    user_type: str,
    code: str,
    method: str,
) -> dict:
    record, _, _ = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if method == "email" and not EMAIL_ENABLED:
        return {"success": False, "message": messages.EMAIL_SYSTEM_DISABLED}
    if method == "sms" and not SMS_ENABLED:
        return {"success": False, "message": messages.SMS_SYSTEM_DISABLED}

    if method == "authenticator" and not record.two_factor_secret:
        return {"success": False, "message": messages.SETUP_AUTHENTICATOR_FIRST}

    verified = await verify_2fa_code(db, record.id, record, method, code, "2fa_setup")
    if not verified:
        return {"success": False, "message": messages.INVALID_OTP}

    secret = record.two_factor_secret if method == "authenticator" else None
    await _update_2fa(db, user_id, user_type, enabled=True, method=method, secret=secret)
    await db.commit()

    return {"success": True, "message": messages.TWO_FACTOR_ENABLED_SUCCESS}


async def disable_2fa(db: AsyncSession, user_id: str, user_type: str) -> dict:
    record, _, _ = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if not record.two_factor_enabled:
        return {"success": False, "message": messages.TWO_FACTOR_NOT_ENABLED}

    await _clear_2fa(db, user_id, user_type)
    await db.commit()

    return {"success": True, "message": messages.TWO_FACTOR_DISABLED_SUCCESS}


async def change_2fa_method(
    db: AsyncSession,
    user_id: str,
    user_type: str,
    new_method: str,
) -> dict:
    record, _, _ = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if not record.two_factor_enabled:
        return {"success": False, "message": messages.TWO_FACTOR_NOT_ENABLED}

    if record.two_factor_method == new_method:
        return {"success": False, "message": messages.ALREADY_USING_METHOD}

    if new_method == "email" and not EMAIL_ENABLED:
        return {"success": False, "message": messages.EMAIL_SYSTEM_DISABLED}
    if new_method == "sms" and not SMS_ENABLED:
        return {"success": False, "message": messages.SMS_SYSTEM_DISABLED}

    if new_method == "authenticator" and not record.two_factor_secret:
        return {"success": False, "message": messages.SETUP_AUTHENTICATOR_FIRST}

    secret = record.two_factor_secret if new_method == "authenticator" else None
    await _update_2fa(db, user_id, user_type, enabled=True, method=new_method, secret=secret)
    await db.commit()

    return {"success": True, "message": messages.TWO_FACTOR_METHOD_CHANGED.format(new_method)}
