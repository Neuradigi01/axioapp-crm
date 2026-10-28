from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.models.otp import OtpRequest


async def get_valid_otp(
    db: AsyncSession, member_id: int, otp_code: str, purpose: str
) -> OtpRequest | None:
    stmt = select(OtpRequest).where(
        OtpRequest.member_id == member_id,
        OtpRequest.otp_code == otp_code,
        OtpRequest.purpose == purpose,
        OtpRequest.is_used == False,
        OtpRequest.expires_at > func.now(),
    )
    return (await db.execute(stmt)).scalar_one_or_none()
