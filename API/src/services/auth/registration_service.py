import random
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.logger import logger
from src.core.security.password import hash_password
from src.models.user import UserLogin, UserInfo
from src.data_access import user_da, admin_da
from src.providers import email_provider
from src.app.shared.providers import captcha as captcha_provider
from src.services.security.verification_service import validate_otp_token, send_post_registration_verification
from src.schemas.auth import RegisterRequest
from src.constants import messages
from config import EMAIL_ENABLED, SMS_ENABLED, CAPTCHA_TYPE, CONTACT_VERIFICATION_MODE


def _generate_user_id() -> str:
    return f"USR{''.join(random.choices('0123456789', k=8))}"


async def verify_captcha_input(captcha_token: str | None, captcha_answer: str | None) -> dict | None:
    """Validate captcha based on CAPTCHA_TYPE. Returns error dict or None if valid."""
    if CAPTCHA_TYPE == "image":
        if not captcha_token or not captcha_answer:
            return {"success": False, "message": messages.CAPTCHA_REQUIRED}
        if not captcha_provider.verify_captcha(captcha_token, captcha_answer):
            return {"success": False, "message": messages.INVALID_CAPTCHA}
    elif CAPTCHA_TYPE in ("recaptcha_v2", "recaptcha_v3"):
        if not captcha_token:
            return {"success": False, "message": messages.CAPTCHA_REQUIRED}
        if not await captcha_provider.verify_recaptcha(captcha_token):
            return {"success": False, "message": messages.INVALID_CAPTCHA}
    return None


async def register_user(db: AsyncSession, req: RegisterRequest) -> dict:
    captcha_err = await verify_captcha_input(req.captcha_token, req.captcha_answer)
    if captcha_err:
        return captcha_err

    email_verified = False
    mobile_verified = False

    if CONTACT_VERIFICATION_MODE == "pre":
        if EMAIL_ENABLED:
            if not req.email_otp_token or not req.email_otp_code:
                return {"success": False, "message": messages.EMAIL_VERIFICATION_REQUIRED}
            token_err = validate_otp_token(req.email_otp_token, req.email_otp_code, "email", req.email)
            if token_err:
                return {"success": False, "message": token_err}
            email_verified = True

        if SMS_ENABLED:
            if not req.mobile_otp_token or not req.mobile_otp_code:
                return {"success": False, "message": messages.MOBILE_VERIFICATION_REQUIRED}
            if not req.mobile_no:
                return {"success": False, "message": messages.MOBILE_VERIFICATION_REQUIRED}
            token_err = validate_otp_token(req.mobile_otp_token, req.mobile_otp_code, "sms", req.mobile_no)
            if token_err:
                return {"success": False, "message": token_err}
            mobile_verified = True

    if await user_da.get_user_info_by_email(db, req.email):
        return {"success": False, "message": messages.EMAIL_EXISTS}

    if await admin_da.get_by_email(db, req.email):
        return {"success": False, "message": messages.EMAIL_EXISTS}

    referrer_member_id = None
    if req.referral_id:
        referrer = await user_da.get_by_user_id(db, req.referral_id)
        if not referrer:
            return {"success": False, "message": messages.INVALID_REFERRAL_ID}
        referrer_member_id = referrer.id

    user_id = _generate_user_id()
    while await user_da.get_by_user_id(db, user_id):
        user_id = _generate_user_id()

    user_login = UserLogin(
        user_id=user_id,
        password=hash_password(req.password),
    )
    db.add(user_login)
    await db.flush()

    user_info = UserInfo(
        member_id=user_login.id,
        first_name=req.first_name,
        last_name=req.last_name,
        email=req.email,
        mobile_no=req.mobile_no or "",
        country_id=req.country_id,
        state_id=req.state_id,
        referral_id=str(referrer_member_id) if referrer_member_id else "",
        is_email_verified=email_verified,
        is_mobile_verified=mobile_verified,
    )
    db.add(user_info)
    await db.commit()

    try:
        await email_provider.send_welcome_email(req.email, user_id, req.first_name)
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")

    if CONTACT_VERIFICATION_MODE == "post" and EMAIL_ENABLED:
        try:
            await send_post_registration_verification(req.email, user_id, req.first_name)
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
        return {"success": True, "message": messages.REGISTRATION_SUCCESS_VERIFY_EMAIL, "data": {"user_id": user_id}}

    return {"success": True, "message": messages.REGISTRATION_SUCCESS, "data": {"user_id": user_id}}
