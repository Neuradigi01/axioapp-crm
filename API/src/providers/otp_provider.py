from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, OTP_EXPIRY_MINUTES, SMS_ENABLED
from src.core.logger import logger
from src.data_access import otp_da
from src.models.otp import OtpRequest
from src.providers import email_provider, sms_provider
from src.utilities.app_utils import generate_otp


async def send_otp_email(
    db: AsyncSession, member_id: int, user_type: str, email: str, purpose: str
) -> str:
    if not EMAIL_ENABLED:
        raise ValueError("Email system is not enabled!")
    otp_code = generate_otp()
    db.add(
        OtpRequest(
            member_id=member_id,
            user_type=user_type,
            otp_code=otp_code,
            method="email",
            purpose=purpose,
            sent_to=email,
            expires_at=datetime.now(UTC) + timedelta(minutes=OTP_EXPIRY_MINUTES),
        )
    )
    await db.flush()
    await email_provider.send_otp_email(email, otp_code, purpose)
    logger.info(f"OTP email sent to {email} for {purpose} (member_id: {member_id})")
    return otp_code


async def send_otp_sms(
    db: AsyncSession, member_id: int, user_type: str, mobile_no: str, purpose: str
) -> str:
    if not SMS_ENABLED:
        raise ValueError("SMS system is not enabled!")
    otp_code = generate_otp()
    db.add(
        OtpRequest(
            member_id=member_id,
            user_type=user_type,
            otp_code=otp_code,
            method="sms",
            purpose=purpose,
            sent_to=mobile_no,
            expires_at=datetime.now(UTC) + timedelta(minutes=OTP_EXPIRY_MINUTES),
        )
    )
    await db.flush()
    await sms_provider.send_otp_sms(mobile_no, otp_code, purpose)
    logger.info(f"OTP SMS sent to {mobile_no} for {purpose} (member_id: {member_id})")
    return otp_code


async def verify_otp(db: AsyncSession, member_id: int, otp_code: str, purpose: str) -> bool:
    otp_record = await otp_da.get_valid_otp(db, member_id, otp_code, purpose)
    if not otp_record:
        return False
    otp_record.is_used = True
    await db.flush()
    return True
