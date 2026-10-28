from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.location import Country, State


async def get_all_countries(db: AsyncSession) -> list[Country]:
    stmt = select(Country).where(Country.is_active == True).order_by(Country.name)
    return list((await db.execute(stmt)).scalars().all())


async def get_states_by_country(db: AsyncSession, country_id: int) -> list[State]:
    stmt = (
        select(State)
        .where(State.country_id == country_id, State.is_active == True)
        .order_by(State.name)
    )
    return list((await db.execute(stmt)).scalars().all())
