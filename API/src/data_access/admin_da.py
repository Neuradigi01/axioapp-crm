from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data_access import generic_da
from src.models.admin import Admin
from src.models.routes import AdminRoute


async def get_by_user_id(db: AsyncSession, admin_user_id: str) -> Admin | None:
    stmt = select(Admin).where(func.lower(Admin.admin_user_id) == admin_user_id.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_id(db: AsyncSession, admin_id: int) -> Admin | None:
    stmt = select(Admin).where(Admin.id == admin_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> Admin | None:
    stmt = select(Admin).where(func.lower(Admin.email) == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_password(db: AsyncSession, admin_user_id: str, hashed_password: str):
    await generic_da.update_password(db, Admin, Admin.admin_user_id, admin_user_id, hashed_password)


async def get_total_admin_count(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Admin)
    return (await db.execute(stmt)).scalar()


async def update_two_factor(
    db: AsyncSession,
    admin_user_id: str,
    *,
    two_factor_enabled: bool,
    two_factor_method: str | None,
    two_factor_secret: str | None = None,
):
    await generic_da.update_two_factor(
        db,
        Admin,
        Admin.admin_user_id,
        admin_user_id,
        two_factor_enabled=two_factor_enabled,
        two_factor_method=two_factor_method,
        two_factor_secret=two_factor_secret,
    )


async def set_two_factor_secret(db: AsyncSession, admin_user_id: str, secret: str):
    await generic_da.set_two_factor_secret(db, Admin, Admin.admin_user_id, admin_user_id, secret)


async def clear_two_factor(db: AsyncSession, admin_user_id: str):
    await generic_da.clear_two_factor(db, Admin, Admin.admin_user_id, admin_user_id)


async def update_profile_image(
    db: AsyncSession, admin_user_id: str, profile_image: str | None
) -> bool:
    stmt = (
        update(Admin)
        .where(func.lower(Admin.admin_user_id) == admin_user_id.strip().lower())
        .values(profile_image=profile_image)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def get_sub_admin_count(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(Admin).where(Admin.is_super_admin == False)
    return (await db.execute(stmt)).scalar()


async def update_profile(
    db: AsyncSession, admin_user_id: str, email: str | None, mobile_no: str | None
) -> bool:
    stmt = (
        update(Admin)
        .where(func.lower(Admin.admin_user_id) == admin_user_id.strip().lower())
        .values(email=email, mobile_no=mobile_no)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def get_sub_admins_paginated(
    db: AsyncSession,
    search: str | None,
    status: bool | None,
    page_index: int,
    page_size: int,
    created_by: int | None = None,
) -> tuple[list[Admin], int]:
    base = select(Admin).where(Admin.is_super_admin == False)

    if created_by is not None:
        base = base.where(Admin.created_by == created_by)

    if status is not None:
        base = base.where(Admin.is_active == status)

    if search:
        term = f"%{search.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(Admin.admin_user_id).like(term),
                func.lower(Admin.name).like(term),
                func.lower(Admin.email).like(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base.options(selectinload(Admin.admin_routes))
        .order_by(Admin.created_at.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def create_admin(db: AsyncSession, admin: Admin) -> Admin:
    db.add(admin)
    await db.flush()
    return admin


async def get_admin_with_routes(db: AsyncSession, admin_user_id: str) -> Admin | None:
    stmt = (
        select(Admin)
        .options(selectinload(Admin.admin_routes))
        .where(func.lower(Admin.admin_user_id) == admin_user_id.strip().lower())
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_sub_admin(
    db: AsyncSession, admin_user_id: str, name: str, email: str | None, mobile_no: str | None
) -> bool:
    stmt = (
        update(Admin)
        .where(func.lower(Admin.admin_user_id) == admin_user_id.strip().lower())
        .values(name=name, email=email, mobile_no=mobile_no)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def delete_admin_routes(db: AsyncSession, admin_id: int) -> bool:
    stmt = delete(AdminRoute).where(AdminRoute.admin_id == admin_id)
    result = await db.execute(stmt)
    return result.rowcount > 0


async def insert_admin_routes(
    db: AsyncSession, admin_id: int, route_ids: list[int], assigned_by: int
):
    for route_id in route_ids:
        db.add(AdminRoute(admin_id=admin_id, route_id=route_id, assigned_by=assigned_by))
    await db.flush()


async def get_admins_by_ids(db: AsyncSession, ids: list[int]) -> list[Admin]:
    if not ids:
        return []
    stmt = select(Admin).where(Admin.id.in_(ids))
    return list((await db.execute(stmt)).scalars().all())


async def update_status(db: AsyncSession, admin_user_id: str, is_active: bool):
    await generic_da.update_status(db, Admin, Admin.admin_user_id, admin_user_id, is_active)
