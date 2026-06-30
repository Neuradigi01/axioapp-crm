from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device_token import DeviceToken


async def register_token(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    fcm_token: str,
    device_info: str | None,
) -> DeviceToken:
    stmt = select(DeviceToken).where(DeviceToken.fcm_token == fcm_token)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.member_id = member_id
        existing.user_type = user_type
        existing.device_info = device_info
        existing.is_active = True
        return existing

    token = DeviceToken(
        member_id=member_id,
        user_type=user_type,
        fcm_token=fcm_token,
        device_info=device_info,
    )
    db.add(token)
    return token


async def unregister_token(db: AsyncSession, fcm_token: str) -> bool:
    stmt = update(DeviceToken).where(DeviceToken.fcm_token == fcm_token).values(is_active=False)
    result = await db.execute(stmt)
    return result.rowcount > 0


async def get_active_tokens_for_user(db: AsyncSession, member_id: int, user_type: str) -> list[str]:
    stmt = select(DeviceToken.fcm_token).where(
        DeviceToken.member_id == member_id,
        DeviceToken.user_type == user_type,
        DeviceToken.is_active == True,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_tokens(db: AsyncSession, tokens: list[str]) -> bool:
    stmt = delete(DeviceToken).where(DeviceToken.fcm_token.in_(tokens))
    result = await db.execute(stmt)
    return result.rowcount > 0
