from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.newsletter import Newsletter


async def subscribe(db: AsyncSession, email: str) -> Newsletter:
    stmt = select(Newsletter).where(Newsletter.email == email)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.is_subscribed = True
        return existing

    record = Newsletter(email=email)
    db.add(record)
    return record


async def unsubscribe(db: AsyncSession, email: str) -> bool:
    stmt = select(Newsletter).where(Newsletter.email == email)
    record = (await db.execute(stmt)).scalar_one_or_none()

    if not record:
        return False

    record.is_subscribed = False
    return True


async def get_subscribers_paginated(
    db: AsyncSession,
    search: str,
    status: str,
    page_index: int,
    page_size: int,
) -> tuple[list[Newsletter], int]:
    base = select(Newsletter)

    if status == "subscribed":
        base = base.where(Newsletter.is_subscribed.is_(True))
    elif status == "unsubscribed":
        base = base.where(Newsletter.is_subscribed.is_(False))

    if search:
        term = f"%{search.strip().lower()}%"
        base = base.where(func.lower(Newsletter.email).like(term))

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base
        .order_by(Newsletter.created_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total
