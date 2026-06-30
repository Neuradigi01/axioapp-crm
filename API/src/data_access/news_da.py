from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.news import News


async def get_news_paginated(
    db: AsyncSession,
    search: str,
    status: str,
    user_type_filter: str,
    page_index: int,
    page_size: int,
) -> tuple[list[News], int]:
    base = select(News)

    if status == "active":
        base = base.where(News.is_active.is_(True))
    elif status == "inactive":
        base = base.where(News.is_active.is_(False))

    if user_type_filter != "all":
        base = base.where(News.user_type == user_type_filter)

    if search:
        term = f"%{search.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(News.heading).like(term),
                func.lower(News.details).like(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base.order_by(News.created_at.desc()).offset(page_index * page_size).limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def get_active_news(db: AsyncSession, user_type: str) -> list[News]:
    stmt = (
        select(News)
        .where(
            News.is_active.is_(True),
            or_(News.user_type == "All", News.user_type == user_type),
        )
        .order_by(News.priority.desc(), News.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_news(db: AsyncSession, **kwargs) -> News:
    record = News(**kwargs)
    db.add(record)
    await db.flush()
    return record


async def update_news(db: AsyncSession, news_id: int, **kwargs) -> News | None:
    stmt = select(News).where(News.id == news_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        return None

    for key, value in kwargs.items():
        setattr(record, key, value)

    return record


async def toggle_news_status(db: AsyncSession, news_id: int) -> News | None:
    stmt = select(News).where(News.id == news_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        return None

    record.is_active = not record.is_active
    return record


async def delete_news(db: AsyncSession, news_id: int) -> bool:
    stmt = delete(News).where(News.id == news_id)
    result = await db.execute(stmt)
    return result.rowcount > 0
