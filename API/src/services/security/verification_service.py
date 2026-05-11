import orjson
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.logger import logger
from src.providers import email_provider, sms_provider
from src.data_access import user_da
from src.utilities.fernet_util import fernet
from src.utilities.app_utils import generate_otp
from src.constants import messages
from config import EMAIL_ENABLED, SMS_ENABLED, OTP_EXPIRY_MINUTES, FRONTEND_URL
from src.schemas.auth import SendContactOtpRequest


async def send_contact_otp(req: SendContactOtpRequest) -> dict:
    if req.type == "email":
        if not EMAIL_ENABLED:
            return {"success": False, "message": messages.EMAIL_SYSTEM_DISABLED}
    else:
        if not SMS_ENABLED:
            return {"success": False, "message": messages.SMS_SYSTEM_DISABLED}

    otp_code = generate_otp()
    expires_at = int((datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)).timestamp())
    token_data = orjson.dumps({"type": req.type, "value": req.value, "otp": otp_code, "expires_at": expires_at}).decode()
    otp_token = fernet.encrypt(token_data)

    if req.type == "email":
        await email_provider.send_otp_email(req.value, otp_code, "registration")
    else:
        await sms_provider.send_otp_sms(req.value, otp_code, "registration")

    return {"success": True, "message": messages.OTP_SENT, "data": {"otp_token": otp_token}}


def generate_email_verification_token(email: str, user_id: str) -> str:
    expires_at = int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
    token_data = orjson.dumps({
        "type": "email_verification",
        "value": email,
        "user_id": user_id,
        "expires_at": expires_at,
    }).decode()
    return fernet.encrypt(token_data)


def validate_email_verification_token(token: str) -> tuple[dict | None, str | None]:
    """Decrypt and validate an email verification token.
    Returns (payload_dict, None) on success or (None, error_message) on failure."""
    try:
        decrypted = orjson.loads(fernet.decrypt(token))
        if decrypted.get("type") != "email_verification":
            return None, messages.VERIFICATION_TOKEN_INVALID
        now = int(datetime.now(timezone.utc).timestamp())
        if now > decrypted.get("expires_at", 0):
            return None, messages.VERIFICATION_TOKEN_INVALID
        return decrypted, None
    except Exception as e:
        logger.error(f"Email verification token validation failed: {e}")
        return None, messages.VERIFICATION_TOKEN_INVALID


async def send_post_registration_verification(email: str, user_id: str, user_name: str = ""):
    token = generate_email_verification_token(email, user_id)
    verification_link = f"{FRONTEND_URL}/accounts/verify-email?token={quote(token, safe='')}"
    await email_provider.send_verification_email(email, verification_link, user_name)


async def verify_email(db: AsyncSession, token: str) -> dict:
    payload, error = validate_email_verification_token(token)
    if error or not payload:
        return {"success": False, "message": error or messages.VERIFICATION_TOKEN_INVALID}

    user = await user_da.get_user_with_info(db, payload["user_id"])
    if not user or not user.user_info:
        return {"success": False, "message": messages.USER_NOT_FOUND}

    if user.user_info.email.lower() != payload["value"].lower():
        return {"success": False, "message": messages.VERIFICATION_EMAIL_MISMATCH}

    await user_da.update_email_verified(db, user.id, True)
    await db.commit()

    return {"success": True, "message": messages.EMAIL_VERIFIED_SUCCESS}


def validate_otp_token(otp_token: str, otp_code: str, expected_type: str, expected_value: str) -> str | None:
    """Decrypt and validate a stateless OTP token.
    Returns None if valid, or an error message string if invalid."""
    try:
        decrypted = orjson.loads(fernet.decrypt(otp_token))
        if decrypted.get("type") != expected_type:
            return messages.VERIFICATION_TOKEN_INVALID
        if decrypted.get("value", "").lower() != expected_value.lower():
            return messages.VERIFICATION_TOKEN_MISMATCH
        if decrypted.get("otp") != otp_code:
            return messages.INVALID_OTP
        now = int(datetime.now(timezone.utc).timestamp())
        if now > decrypted.get("expires_at", 0):
            return messages.VERIFICATION_TOKEN_INVALID
    except Exception as e:
        logger.error(f"OTP token validation failed: {e}")
        return messages.VERIFICATION_TOKEN_INVALID
    return None
