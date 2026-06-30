from sqlalchemy.ext.asyncio import AsyncSession

from src.models.profile_change_history import ProfileChangeHistory


async def insert_history(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    old_data: dict,
    new_data: dict,
):
    record = ProfileChangeHistory(
        member_id=member_id,
        user_type=user_type,
        old_data=old_data,
        new_data=new_data,
    )
    db.add(record)
    await db.flush()
