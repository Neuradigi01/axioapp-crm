from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from src.models.password_reset import PasswordResetToken


async def get_valid_token(db: AsyncSession, token: str) -> PasswordResetToken | None:
    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token == token,
        PasswordResetToken.is_used == False,
        PasswordResetToken.expires_at > func.now(),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def invalidate_user_tokens(db: AsyncSession, member_id: int, user_type: str):
    stmt = (
        update(PasswordResetToken)
        .where(
            PasswordResetToken.member_id == member_id,
            PasswordResetToken.user_type == user_type,
            PasswordResetToken.is_used == False,
        )
        .values(is_used=True)
    )
    await db.execute(stmt)
