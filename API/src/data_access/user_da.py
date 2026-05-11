from datetime import date

from sqlalchemy import select, update, func, cast, Date, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.models.user import UserLogin, UserInfo
from src.data_access import generic_da


async def get_by_user_id(db: AsyncSession, user_id: str) -> UserLogin | None:
    stmt = select(UserLogin).where(func.lower(UserLogin.user_id) == user_id.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_user_with_info(db: AsyncSession, user_id: str) -> UserLogin | None:
    stmt = (
        select(UserLogin)
        .options(selectinload(UserLogin.user_info))
        .where(func.lower(UserLogin.user_id) == user_id.strip().lower())
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_user_by_member_id(db: AsyncSession, member_id: int) -> UserLogin | None:
    stmt = select(UserLogin).where(UserLogin.id == member_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_user_info_by_email(db: AsyncSession, email: str) -> UserInfo | None:
    stmt = select(UserInfo).where(func.lower(UserInfo.email) == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_password(db: AsyncSession, user_id: str, hashed_password: str):
    await generic_da.update_password(db, UserLogin, UserLogin.user_id, user_id, hashed_password)


async def get_user_with_info_by_email(db: AsyncSession, email: str) -> UserLogin | None:
    stmt = (
        select(UserLogin)
        .join(UserInfo, UserLogin.id == UserInfo.member_id)
        .options(selectinload(UserLogin.user_info))
        .where(func.lower(UserInfo.email) == email.strip().lower())
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_total_user_count(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(UserLogin)
    return (await db.execute(stmt)).scalar()


async def get_user_referral_count(db: AsyncSession, member_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(UserInfo)
        .where(UserInfo.referral_id == str(member_id))
    )
    return (await db.execute(stmt)).scalar()


async def update_profile(
    db: AsyncSession, member_id: int, first_name: str, last_name: str,
    email: str, mobile_no: str | None,
    country_id: int | None = None, state_id: int | None = None,
) -> bool:
    stmt = (
        update(UserInfo)
        .where(UserInfo.member_id == member_id)
        .values(
            first_name=first_name,
            last_name=last_name,
            email=email,
            mobile_no=mobile_no,
            country_id=country_id,
            state_id=state_id,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def update_profile_image(db: AsyncSession, member_id: int, profile_image: str | None) -> bool:
    stmt = (
        update(UserInfo)
        .where(UserInfo.member_id == member_id)
        .values(profile_image=profile_image)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def update_two_factor(
    db: AsyncSession, user_id: str, *,
    two_factor_enabled: bool,
    two_factor_method: str | None,
    two_factor_secret: str | None = None,
):
    await generic_da.update_two_factor(
        db, UserLogin, UserLogin.user_id, user_id,
        two_factor_enabled=two_factor_enabled,
        two_factor_method=two_factor_method,
        two_factor_secret=two_factor_secret,
    )


async def set_two_factor_secret(db: AsyncSession, user_id: str, secret: str):
    await generic_da.set_two_factor_secret(db, UserLogin, UserLogin.user_id, user_id, secret)


async def clear_two_factor(db: AsyncSession, user_id: str):
    await generic_da.clear_two_factor(db, UserLogin, UserLogin.user_id, user_id)


async def get_user_count_by_status(db: AsyncSession, is_active: bool) -> int:
    stmt = select(func.count()).select_from(UserLogin).where(UserLogin.is_active == is_active)
    return (await db.execute(stmt)).scalar()


async def get_today_registration_count(db: AsyncSession) -> int:
    today = date.today()
    stmt = (
        select(func.count())
        .select_from(UserInfo)
        .where(cast(UserInfo.joining_date, Date) == today)
    )
    return (await db.execute(stmt)).scalar()


async def get_recent_registrations(db: AsyncSession, limit: int = 10) -> list[UserInfo]:
    stmt = (
        select(UserInfo)
        .options(selectinload(UserInfo.user_login))
        .order_by(UserInfo.joining_date.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_users_paginated(
    db: AsyncSession,
    search: str | None,
    status: bool | None,
    date_from: str | None,
    date_to: str | None,
    page_index: int,
    page_size: int,
) -> tuple[list[UserInfo], int]:
    base = select(UserInfo).join(UserLogin, UserLogin.id == UserInfo.member_id)

    if status is not None:
        base = base.where(UserLogin.is_active == status)

    if search:
        term = f"%{search.strip().lower()}%"
        base = base.where(
            or_(
                func.lower(UserLogin.user_id).like(term),
                func.lower(UserInfo.first_name).like(term),
                func.lower(UserInfo.last_name).like(term),
                func.lower(UserInfo.email).like(term),
            )
        )

    if date_from:
        base = base.where(cast(UserInfo.joining_date, Date) >= date_from)

    if date_to:
        base = base.where(cast(UserInfo.joining_date, Date) <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar()

    items_stmt = (
        base
        .options(selectinload(UserInfo.user_login))
        .order_by(UserInfo.joining_date.desc())
        .offset(page_index * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return items, total


async def get_user_full_detail(db: AsyncSession, user_id: str) -> UserInfo | None:
    stmt = (
        select(UserInfo)
        .join(UserLogin, UserLogin.id == UserInfo.member_id)
        .options(selectinload(UserInfo.user_login))
        .where(func.lower(UserLogin.user_id) == user_id.strip().lower())
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_email_verified(db: AsyncSession, member_id: int, is_verified: bool) -> bool:
    stmt = (
        update(UserInfo)
        .where(UserInfo.member_id == member_id)
        .values(is_email_verified=is_verified)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def get_users_by_ids(db: AsyncSession, ids: list[int]) -> list[UserLogin]:
    if not ids:
        return []
    stmt = select(UserLogin).where(UserLogin.id.in_(ids))
    return list((await db.execute(stmt)).scalars().all())


async def update_status(db: AsyncSession, user_id: str, is_active: bool):
    await generic_da.update_status(db, UserLogin, UserLogin.user_id, user_id, is_active)
