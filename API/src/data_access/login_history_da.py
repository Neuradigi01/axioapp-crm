from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.login_history import LoginHistory


async def get_by_id(db: AsyncSession, record_id: int) -> LoginHistory | None:
    stmt = select(LoginHistory).where(LoginHistory.id == record_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def is_token_active(db: AsyncSession, token_id: int) -> bool:
    stmt = select(LoginHistory.is_token_active).where(LoginHistory.id == token_id)
    result = (await db.execute(stmt)).scalar_one_or_none()
    return result is True


async def invalidate_token(
    db: AsyncSession,
    token_id: int,
    logout_by_id: int,
    logout_by_type: str,
    remarks: str = "Logged out",
) -> bool:
    """Mark a token as inactive. Returns True if the token was active and invalidated."""
    now = datetime.now(UTC)
    stmt = (
        update(LoginHistory)
        .where(and_(LoginHistory.id == token_id, LoginHistory.is_token_active == True))
        .values(
            is_token_active=False,
            logout_timestamp=now,
            logout_remarks=remarks,
            logout_by_id=logout_by_id,
            logout_by_type=logout_by_type,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def get_login_history(
    db: AsyncSession,
    user_id: str | None = None,
    match_exact: bool = True,
    page_index: int = 0,
    page_size: int = 50,
) -> tuple[list[LoginHistory], int]:
    """Get paginated login history. Returns (records, total_count)."""
    base = select(LoginHistory)
    count_base = select(func.count(LoginHistory.id))

    if user_id:
        if match_exact:
            condition = func.lower(LoginHistory.user_id) == user_id.strip().lower()
        else:
            condition = func.lower(LoginHistory.user_id).contains(user_id.strip().lower())
        base = base.where(condition)
        count_base = count_base.where(condition)

    total = (await db.execute(count_base)).scalar() or 0

    stmt = base.order_by(LoginHistory.id.desc()).offset(page_index * page_size).limit(page_size)
    records = (await db.execute(stmt)).scalars().all()

    return list(records), total


async def mark_expired_tokens(db: AsyncSession, token_validity_hours: int = 24):
    """Auto-mark tokens as expired if their login_at + validity has passed."""
    now = datetime.now(UTC)
    from sqlalchemy import text

    stmt = (
        update(LoginHistory)
        .where(
            and_(
                LoginHistory.is_token_active == True,
                LoginHistory.login_at + text(f"interval '{token_validity_hours} hours'") <= now,
            )
        )
        .values(
            is_token_active=False,
            logout_timestamp=now,
            logout_remarks="Expired",
        )
    )
    await db.execute(stmt)
