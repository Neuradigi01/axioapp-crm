from sqlalchemy.ext.asyncio import AsyncSession
from src.core.logger import logger
from src.core.security.jwt import create_access_token
from src.core.security.password import verify_password
from src.models.user import UserLogin
from src.models.login_history import LoginHistory
from src.data_access import user_da, admin_da, route_da
from src.providers import otp_provider, two_factor_provider
from src.services.auth.resolver_service import resolve_user, resolve_admin, resolve_record, get_available_2fa_methods
from src.services.auth.registration_service import verify_captcha_input
from src.services.security.verification_service import send_post_registration_verification
from src.constants import messages
from src.constants.route_ids import RouteIds
from config import EMAIL_ENABLED, SMS_ENABLED, CONTACT_VERIFICATION_MODE


async def _handle_2fa(
    db: AsyncSession, record, user_type: str,
    email: str | None, mobile: str | None, two_factor_code: str | None,
    two_factor_method: str | None = None,
) -> dict | None:
    """Handle 2FA verification during login. Returns a response dict if 2FA
    blocks login (needs code or code invalid), or None if 2FA passed / not required."""
    if not record.two_factor_enabled:
        return None

    available_methods = get_available_2fa_methods(record, email, mobile)
    preferred = record.two_factor_method if record.two_factor_method in available_methods else (available_methods[0] if available_methods else None)

    if not preferred:
        return {"success": False, "message": messages.NO_2FA_METHOD_AVAILABLE}

    if not two_factor_code:
        result = {"success": False, "data": {"requires_2fa": True, "method": preferred, "available_methods": available_methods}}
        if preferred == "email":
            await otp_provider.send_otp_email(db, record.id, user_type, email, "login")
        elif preferred == "sms":
            await otp_provider.send_otp_sms(db, record.id, user_type, mobile, "login")
        await db.commit()
        return result

    # Use the method passed from the client (e.g. after "try another way"),
    # falling back to the DB-stored preferred method
    method = two_factor_method if two_factor_method and two_factor_method in available_methods else preferred

    verified = False
    if method == "authenticator":
        verified = two_factor_provider.verify_totp_code(record.two_factor_secret, two_factor_code)
    elif method in ("email", "sms"):
        verified = await otp_provider.verify_otp(db, record.id, two_factor_code, "login")

    if not verified:
        return {"success": False, "message": messages.INVALID_OTP}

    return None


async def try_another_way(
    db: AsyncSession, identifier: str, password: str,
    user_type: str, method: str,
) -> dict:
    record, user_id, email, mobile = await resolve_record(db, identifier, user_type)

    if not record or not record.is_active:
        return {"success": False, "message": messages.INVALID_CREDENTIALS}
    if not verify_password(password, record.password):
        return {"success": False, "message": messages.INVALID_CREDENTIALS}
    if not record.two_factor_enabled:
        return {"success": False, "message": messages.TWO_FACTOR_NOT_ENABLED}

    available_methods = get_available_2fa_methods(record, email, mobile)

    if method not in available_methods:
        return {"success": False, "message": messages.METHOD_NOT_AVAILABLE}
    if method == "email" and not EMAIL_ENABLED:
        return {"success": False, "message": messages.EMAIL_SYSTEM_DISABLED}
    if method == "sms" and not SMS_ENABLED:
        return {"success": False, "message": messages.SMS_SYSTEM_DISABLED}

    if method == "authenticator":
        return {"success": True, "message": messages.OK, "data": {"method": "authenticator", "available_methods": available_methods}}
    elif method == "email":
        await otp_provider.send_otp_email(db, record.id, user_type, email, "login")
        await db.commit()
        return {"success": True, "message": messages.OTP_SENT_EMAIL, "data": {"method": "email", "available_methods": available_methods}}
    elif method == "sms":
        await otp_provider.send_otp_sms(db, record.id, user_type, mobile, "login")
        await db.commit()
        return {"success": True, "message": messages.OTP_SENT_PHONE, "data": {"method": "sms", "available_methods": available_methods}}

    return {"success": False, "message": messages.INVALID_METHOD}


async def _create_login_record(
    db: AsyncSession,
    user_id: str,
    user_type: str,
    ip_address: str,
    sender_ip: str,
    ip_info: dict | None,
    device_info: dict | None,
) -> LoginHistory:
    record = LoginHistory(
        user_id=user_id,
        user_type=user_type,
        ip_address=ip_address,
        sender_ip=sender_ip,
        ip_info=ip_info,
        device_info=device_info,
    )
    db.add(record)
    await db.flush()
    return record


async def authenticate_user(
    db: AsyncSession,
    identifier: str,
    password: str,
    ip_address: str = "",
    sender_ip: str = "",
    ip_info: dict | None = None,
    device_info: dict | None = None,
    two_factor_code: str | None = None,
    two_factor_method: str | None = None,
    captcha_token: str | None = None,
    captcha_answer: str | None = None,
) -> dict:
    if not two_factor_code:
        captcha_err = await verify_captcha_input(captcha_token, captcha_answer)
        if captcha_err:
            return captcha_err

    user = await resolve_user(db, identifier)
    if not user or not user.is_active:
        # Record failed attempt with unknown user_id
        record = await _create_login_record(db, identifier, "User", ip_address, sender_ip, ip_info, device_info)
        await db.commit()
        return {"success": False, "message": messages.INVALID_CREDENTIALS}

    if not verify_password(password, user.password):
        record = await _create_login_record(db, user.user_id, "User", ip_address, sender_ip, ip_info, device_info)
        await db.commit()
        return {"success": False, "message": messages.INVALID_CREDENTIALS}

    email = user.user_info.email if user.user_info else None
    mobile = user.user_info.mobile_no if user.user_info else None
    tfa_result = await _handle_2fa(db, user, "User", email, mobile, two_factor_code, two_factor_method)
    if tfa_result is not None:
        return tfa_result

    if CONTACT_VERIFICATION_MODE != "none" and EMAIL_ENABLED:
        if user.user_info and not user.user_info.is_email_verified:
            try:
                await send_post_registration_verification(
                    email, user.user_id, user.user_info.first_name,
                )
            except Exception as e:
                logger.error(f"Failed to resend verification email: {e}")
            return {
                "success": False,
                "message": messages.EMAIL_NOT_VERIFIED,
                "data": {"requires_email_verification": True},
            }

    return await _complete_user_login(db, user, ip_address, sender_ip, ip_info, device_info)


async def authenticate_admin(
    db: AsyncSession,
    identifier: str,
    password: str,
    ip_address: str = "",
    sender_ip: str = "",
    ip_info: dict | None = None,
    device_info: dict | None = None,
    two_factor_code: str | None = None,
    two_factor_method: str | None = None,
    captcha_token: str | None = None,
    captcha_answer: str | None = None,
) -> dict:
    if not two_factor_code:
        captcha_err = await verify_captcha_input(captcha_token, captcha_answer)
        if captcha_err:
            return captcha_err

    admin = await resolve_admin(db, identifier)
    if not admin or not admin.is_active:
        record = await _create_login_record(db, identifier, "Admin", ip_address, sender_ip, ip_info, device_info)
        await db.commit()
        return {"success": False, "message": messages.INVALID_CREDENTIALS}

    if not verify_password(password, admin.password):
        record = await _create_login_record(db, admin.admin_user_id, "Admin", ip_address, sender_ip, ip_info, device_info)
        await db.commit()
        return {"success": False, "message": messages.INVALID_CREDENTIALS}

    tfa_result = await _handle_2fa(db, admin, "Admin", admin.email, admin.mobile_no, two_factor_code, two_factor_method)
    if tfa_result is not None:
        return tfa_result

    # Create login history record, get its ID for the JWT token
    record = await _create_login_record(db, admin.admin_user_id, "Admin", ip_address, sender_ip, ip_info, device_info)
    record.is_valid_credentials = True
    record.is_login_successful = True
    record.is_token_active = True

    access_rights = await _build_admin_access_rights(db, admin.id, admin.is_super_admin, admin.is_developer)
    token = create_access_token({
        "token_id": record.id,
        "user_id": admin.admin_user_id,
        "role": "Admin",
        "access_rights": access_rights,
        "is_super_admin": admin.is_super_admin,
    })

    await db.commit()

    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "token": token,
            "user_id": admin.admin_user_id,
            "role": "Admin",
            "name": admin.name,
            "email": admin.email or "",
            "is_super_admin": admin.is_super_admin,
        },
    }


async def _complete_user_login(
    db: AsyncSession,
    user: UserLogin,
    ip_address: str,
    sender_ip: str,
    ip_info: dict | None,
    device_info: dict | None,
    admin_token_id: int | None = None,
) -> dict:
    """Shared tail for user login: create history record, build token, return response."""
    record = await _create_login_record(db, user.user_id, "User", ip_address, sender_ip, ip_info, device_info)
    record.is_valid_credentials = True
    record.is_login_successful = True
    record.is_token_active = True
    if admin_token_id is not None:
        record.by_admin_token_id = admin_token_id

    access_rights = await _build_user_access_rights(db)
    token = create_access_token({
        "token_id": record.id,
        "user_id": user.user_id,
        "role": "User",
        "access_rights": access_rights,
    })

    await db.commit()

    return {
        "success": True,
        "message": messages.OK,
        "data": {
            "token": token,
            "user_id": user.user_id,
            "role": "User",
            "first_name": user.user_info.first_name if user.user_info else "",
            "last_name": user.user_info.last_name if user.user_info else "",
            "email": user.user_info.email if user.user_info else "",
        },
    }


async def impersonate_user(
    db: AsyncSession,
    user_id: str,
    admin_token_id: int,
    ip_address: str = "",
    sender_ip: str = "",
    ip_info: dict | None = None,
    device_info: dict | None = None,
) -> dict:
    """Generate a user token for admin impersonation. No password or 2FA check."""
    user = await resolve_user(db, user_id)
    if not user:
        return {"success": False, "message": messages.IMPERSONATE_USER_NOT_FOUND}

    return await _complete_user_login(db, user, ip_address, sender_ip, ip_info, device_info, admin_token_id)


async def _build_user_access_rights(db: AsyncSession) -> str:
    route_ids = await route_da.get_route_ids_by_user_types(db, ["User", "Any"])
    return ",".join(str(r) for r in route_ids)


async def _build_admin_access_rights(db: AsyncSession, admin_id: int, is_super_admin: bool, is_developer: bool) -> str:
    if is_super_admin:
        route_ids = await route_da.get_route_ids_by_user_types(db, ["Admin", "Any"])
    else:
        assigned_ids = await route_da.get_admin_route_ids(db, admin_id)
        compulsory_ids = await route_da.get_compulsory_route_ids(db, ["Admin", "Any"])
        route_ids = list(set(assigned_ids + compulsory_ids))

    if not is_developer:
        route_ids = [r for r in route_ids if r not in RouteIds.DEVELOPER_ONLY]

    return ",".join(str(r) for r in route_ids)
