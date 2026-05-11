from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.contact_us import ContactUs


async def create_contact(db: AsyncSession, **kwargs) -> ContactUs:
    contact = ContactUs(**kwargs)
    db.add(contact)
    return contact


async def get_contacts_paginated(
    db: AsyncSession,
    search: str,
    type_filter: str,
    page_index: int,
    page_size: int,
) -> tuple[list[ContactUs], int]:
    base = select(ContactUs)

    if type_filter and type_filter != "all":
        base = base.where(ContactUs.type == type_filter)

    if search:
        term = f"%{search.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(ContactUs.name).like(term),
                func.lower(ContactUs.email).like(term),
                func.lower(ContactUs.subject).like(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base
        .order_by(ContactUs.created_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total
