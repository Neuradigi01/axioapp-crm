from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, OTP_EXPIRY_MINUTES, SMS_ENABLED
from src.app.core.auth.verification import data_access
from src.providers import email_provider, sms_provider
from src.utilities.app_utils import generate_otp
from src.utilities.fernet_util import fernet

ContactType = Literal["email", "sms"]


class VerificationError(Exception):
    """Raised when a verification operation can't succeed for a reason the
    caller should turn into a 4xx (disabled channel, bad token, mismatch).
    `detail` is the user-facing message; `status_code` is the HTTP status."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class OtpDispatchResult:
    otp_token: str


def _build_otp_token(contact_type: ContactType, value: str, otp_code: str) -> str:
    expires_at = int((datetime.now(UTC) + timedelta(minutes=OTP_EXPIRY_MINUTES)).timestamp())
    payload = orjson.dumps(
        {"type": contact_type, "value": value, "otp": otp_code, "expires_at": expires_at}
    ).decode()
    return fernet.encrypt(payload)


async def send_contact_otp(*, contact_type: ContactType, value: str) -> OtpDispatchResult:
    """Issue a stateless OTP for an unverified contact during registration.

    The OTP code and expiry travel inside a fernet-encrypted token; the
    frontend stores the token and posts it back with the user-typed code
    on form submit. Server validates by decrypting the same token.
    """
    if contact_type == "email" and not EMAIL_ENABLED:
        raise VerificationError("Email system is disabled")
    if contact_type == "sms" and not SMS_ENABLED:
        raise VerificationError("SMS system is disabled")

    otp_code = generate_otp()
    token = _build_otp_token(contact_type, value, otp_code)

    if contact_type == "email":
        await email_provider.send_otp_email(value, otp_code, "registration")
    else:
        await sms_provider.send_otp_sms(value, otp_code, "registration")

    return OtpDispatchResult(otp_token=token)


def validate_otp_token(
    *, otp_token: str, otp_code: str, expected_type: ContactType, expected_value: str
) -> None:
    """Verify a `send_contact_otp` token + the user-supplied code.

    Raises `VerificationError` on any mismatch. Returns nothing on success.
    """
    try:
        payload = orjson.loads(fernet.decrypt(otp_token))
    except Exception:
        raise VerificationError("Invalid verification token")

    if payload.get("type") != expected_type:
        raise VerificationError("Invalid verification token")
    if payload.get("value", "").lower() != expected_value.lower():
        raise VerificationError("Verification target does not match")
    if payload.get("otp") != otp_code:
        raise VerificationError("Invalid OTP code")
    if int(datetime.now(UTC).timestamp()) > int(payload.get("expires_at", 0)):
        raise VerificationError("Verification token has expired")


def build_email_verification_token(*, email: str, user_id: str) -> str:
    """Build a 24-hour fernet token for the click-the-link email verify flow."""
    expires_at = int((datetime.now(UTC) + timedelta(hours=24)).timestamp())
    payload = orjson.dumps(
        {
            "type": "email_verification",
            "value": email,
            "user_id": user_id,
            "expires_at": expires_at,
        }
    ).decode()
    return fernet.encrypt(payload)


async def verify_email_token(db: AsyncSession, token: str) -> None:
    """Consume an email verification token and flip `is_email_verified`.

    Token shape is created by `build_email_verification_token` (or its
    legacy equivalent — they're cross-compatible, same fernet key). On
    success, the corresponding `tbl_user_info` row is updated. Raises
    `VerificationError` on any failure (bad token, expired, unknown
    user, email mismatch).
    """
    try:
        payload = orjson.loads(fernet.decrypt(token))
    except Exception:
        raise VerificationError("Invalid verification token")

    if payload.get("type") != "email_verification":
        raise VerificationError("Invalid verification token")
    if int(datetime.now(UTC).timestamp()) > int(payload.get("expires_at", 0)):
        raise VerificationError("Verification token has expired")

    user_id = payload.get("user_id")
    email_in_token = payload.get("value", "")

    row = await data_access.get_user_id_and_email_by_handle(db, user_id)
    if row is None:
        raise VerificationError("User not found", status_code=404)
    member_id, email = row
    if not email or email.lower() != email_in_token.lower():
        raise VerificationError("Verification email does not match")

    await data_access.mark_email_verified(db, member_id=member_id)
    await db.commit()
