from sqlalchemy import select, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.popup import Popup


async def get_popups_paginated(
    db: AsyncSession,
    status: str,
    user_type_filter: str,
    page_index: int,
    page_size: int,
) -> tuple[list[Popup], int]:
    base = select(Popup)

    if status == "active":
        base = base.where(Popup.is_active.is_(True))
    elif status == "inactive":
        base = base.where(Popup.is_active.is_(False))

    if user_type_filter != "all":
        base = base.where(Popup.user_type == user_type_filter)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base
        .order_by(Popup.created_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def get_active_popup(db: AsyncSession, user_type: str) -> Popup | None:
    stmt = (
        select(Popup)
        .where(
            Popup.is_active.is_(True),
            or_(Popup.user_type == "All", Popup.user_type == user_type),
        )
        .order_by(Popup.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_popup(db: AsyncSession, **kwargs) -> Popup:
    record = Popup(**kwargs)
    db.add(record)
    await db.flush()
    return record


async def toggle_popup_status(db: AsyncSession, popup_id: int) -> Popup | None:
    stmt = select(Popup).where(Popup.id == popup_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        return None

    record.is_active = not record.is_active
    return record


async def delete_popup(db: AsyncSession, popup_id: int) -> Popup | None:
    stmt = select(Popup).where(Popup.id == popup_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        return None

    await db.execute(delete(Popup).where(Popup.id == popup_id))
    return record
