from sqlalchemy.ext.asyncio import AsyncSession

from src.models.password_change_history import PasswordChangeHistory


async def insert_history(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    old_password_hash: str,
    new_password_hash: str,
    change_type: str,
    changed_by_id: int,
):
    record = PasswordChangeHistory(
        member_id=member_id,
        user_type=user_type,
        old_password_hash=old_password_hash,
        new_password_hash=new_password_hash,
        change_type=change_type,
        changed_by_id=changed_by_id,
    )
    db.add(record)
    await db.flush()
