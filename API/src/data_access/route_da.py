from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.routes import AdminRoute, Route


async def get_route_ids_by_user_types(db: AsyncSession, user_types: list[str]) -> list[int]:
    stmt = select(Route.id).where(Route.user_type.in_(user_types), Route.is_active == True)
    return list((await db.execute(stmt)).scalars().all())


async def get_compulsory_route_ids(db: AsyncSession, user_types: list[str]) -> list[int]:
    stmt = select(Route.id).where(
        Route.user_type.in_(user_types),
        Route.is_active == True,
        Route.is_compulsory == True,
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_admin_route_ids(db: AsyncSession, admin_id: int) -> list[int]:
    stmt = select(AdminRoute.route_id).where(AdminRoute.admin_id == admin_id)
    return list((await db.execute(stmt)).scalars().all())


async def get_all(db: AsyncSession) -> list[Route]:
    stmt = select(Route).order_by(Route.id)
    return list((await db.execute(stmt)).scalars().all())


async def get_by_id(db: AsyncSession, route_id: int) -> Route | None:
    stmt = select(Route).where(Route.id == route_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_control_id(db: AsyncSession, control_id: str) -> Route | None:
    stmt = select(Route).where(Route.control_id == control_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_children(db: AsyncSession, parent_id: int) -> list[Route]:
    stmt = select(Route).where(Route.parent_id == parent_id)
    return list((await db.execute(stmt)).scalars().all())


async def cascade_active_status(db: AsyncSession, parent_id: int, is_active: bool):
    stmt = update(Route).where(Route.parent_id == parent_id).values(is_active=is_active)
    await db.execute(stmt)


async def get_non_compulsory_by_user_types(db: AsyncSession, user_types: list[str]) -> list[Route]:
    stmt = (
        select(Route)
        .where(
            Route.user_type.in_(user_types),
            Route.is_active == True,
            Route.is_compulsory == False,
        )
        .order_by(Route.order_no, Route.id)
    )
    return list((await db.execute(stmt)).scalars().all())
