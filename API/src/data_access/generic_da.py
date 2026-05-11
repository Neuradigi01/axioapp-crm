"""
Generic data access functions parameterized by model class.

Eliminates duplication between user_da and admin_da for operations
that have identical logic but differ only in the model and user_id column.
"""

from sqlalchemy import update, func
from sqlalchemy.ext.asyncio import AsyncSession


async def update_password(db: AsyncSession, model, user_id_column, user_id: str, hashed_password: str) -> bool:
    stmt = (
        update(model)
        .where(func.lower(user_id_column) == user_id.strip().lower())
        .values(password=hashed_password)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def update_two_factor(
    db: AsyncSession, model, user_id_column, user_id: str, *,
    two_factor_enabled: bool,
    two_factor_method: str | None,
    two_factor_secret: str | None = None,
) -> bool:
    values: dict = {
        "two_factor_enabled": two_factor_enabled,
        "two_factor_method": two_factor_method,
    }
    if two_factor_secret is not None:
        values["two_factor_secret"] = two_factor_secret
    stmt = (
        update(model)
        .where(func.lower(user_id_column) == user_id.strip().lower())
        .values(**values)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def set_two_factor_secret(db: AsyncSession, model, user_id_column, user_id: str, secret: str) -> bool:
    stmt = (
        update(model)
        .where(func.lower(user_id_column) == user_id.strip().lower())
        .values(two_factor_secret=secret)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def clear_two_factor(db: AsyncSession, model, user_id_column, user_id: str) -> bool:
    stmt = (
        update(model)
        .where(func.lower(user_id_column) == user_id.strip().lower())
        .values(two_factor_enabled=False, two_factor_method=None, two_factor_secret=None)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def update_status(db: AsyncSession, model, user_id_column, user_id: str, is_active: bool) -> bool:
    stmt = (
        update(model)
        .where(func.lower(user_id_column) == user_id.strip().lower())
        .values(is_active=is_active)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0
