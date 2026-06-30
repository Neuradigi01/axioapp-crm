from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import Notification


async def create_notification(db: AsyncSession, **kwargs) -> Notification:
    notification = Notification(**kwargs)
    db.add(notification)
    return notification


async def get_notifications_paginated(
    db: AsyncSession,
    member_id: int,
    user_type: str,
    page_index: int,
    page_size: int,
) -> tuple[list[Notification], int]:
    base = select(Notification).where(
        Notification.member_id == member_id,
        Notification.user_type == user_type,
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base.order_by(Notification.created_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def get_unread_count(db: AsyncSession, member_id: int, user_type: str) -> int:
    stmt = select(func.count()).select_from(
        select(Notification)
        .where(
            Notification.member_id == member_id,
            Notification.user_type == user_type,
            Notification.is_read == False,
        )
        .subquery()
    )
    return (await db.execute(stmt)).scalar()


async def mark_as_read(db: AsyncSession, notification_id: int, member_id: int) -> bool:
    stmt = (
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.member_id == member_id,
        )
        .values(is_read=True)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def mark_all_as_read(db: AsyncSession, member_id: int, user_type: str) -> bool:
    stmt = (
        update(Notification)
        .where(
            Notification.member_id == member_id,
            Notification.user_type == user_type,
            Notification.is_read == False,
        )
        .values(is_read=True)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0
