from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.user import UserLogin
from src.models.admin import Admin


async def resolve_member_id(db: AsyncSession, text_user_id: str, user_type: str) -> int | None:
    """Resolve text user_id to integer member_id/admin_id based on user_type."""
    if user_type == "Admin":
        stmt = select(Admin.id).where(Admin.admin_user_id == text_user_id)
    else:
        stmt = select(UserLogin.id).where(UserLogin.user_id == text_user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_text_user_id(db: AsyncSession, member_id: int, user_type: str) -> str | None:
    """Resolve integer member_id/admin_id back to text user_id."""
    if user_type == "Admin":
        stmt = select(Admin.admin_user_id).where(Admin.id == member_id)
    else:
        stmt = select(UserLogin.user_id).where(UserLogin.id == member_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def batch_resolve_text_user_ids(
    db: AsyncSession, pairs: list[tuple[int, str]],
) -> dict[tuple[int, str], str]:
    """Batch resolve (member_id, user_type) pairs to text user_ids.
    Returns dict mapping (member_id, user_type) -> text_user_id.
    At most 2 queries (one for users, one for admins).
    """
    user_ids = list({mid for mid, utype in pairs if utype == "User"})
    admin_ids = list({mid for mid, utype in pairs if utype == "Admin"})

    result: dict[tuple[int, str], str] = {}

    if user_ids:
        stmt = select(UserLogin.id, UserLogin.user_id).where(UserLogin.id.in_(user_ids))
        for row in (await db.execute(stmt)).all():
            result[(row[0], "User")] = row[1]

    if admin_ids:
        stmt = select(Admin.id, Admin.admin_user_id).where(Admin.id.in_(admin_ids))
        for row in (await db.execute(stmt)).all():
            result[(row[0], "Admin")] = row[1]

    return result
