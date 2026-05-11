from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.action_token import UsedActionToken


async def is_token_used(db: AsyncSession, jti: str) -> bool:
    stmt = select(UsedActionToken.id).where(UsedActionToken.jti == jti)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def mark_token_used(
    db: AsyncSession, jti: str, member_id: int, user_type: str, expires_at: datetime,
):
    db.add(UsedActionToken(
        jti=jti,
        member_id=member_id,
        user_type=user_type,
        expires_at=expires_at,
    ))
    await db.flush()


async def cleanup_expired_tokens(db: AsyncSession):
    stmt = delete(UsedActionToken).where(
        UsedActionToken.expires_at < datetime.now(timezone.utc)
    )
    await db.execute(stmt)
