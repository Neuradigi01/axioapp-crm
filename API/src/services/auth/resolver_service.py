from sqlalchemy.ext.asyncio import AsyncSession

from config import EMAIL_ENABLED, SMS_ENABLED
from src.data_access import admin_da, user_da
from src.models.user import UserLogin


async def resolve_user(db: AsyncSession, identifier: str) -> UserLogin | None:
    user = await user_da.get_user_with_info(db, identifier)
    if user:
        return user
    if "@" in identifier:
        return await user_da.get_user_with_info_by_email(db, identifier)
    return None


async def resolve_admin(db: AsyncSession, identifier: str):
    admin = await admin_da.get_by_user_id(db, identifier)
    if admin:
        return admin
    if "@" in identifier:
        return await admin_da.get_by_email(db, identifier)
    return None


def get_available_2fa_methods(record, email: str | None, mobile: str | None) -> list[str]:
    methods = []
    if EMAIL_ENABLED and email:
        methods.append("email")
    if SMS_ENABLED and mobile:
        methods.append("sms")
    if record.two_factor_secret:
        methods.append("authenticator")
    return methods


async def resolve_record(db: AsyncSession, identifier: str, user_type: str):
    """Resolve a user or admin record by identifier (user_id or email).
    Returns (record, user_id_str, email, mobile) or (None, None, None, None)."""
    if user_type == "User":
        user = await resolve_user(db, identifier)
        if not user:
            return None, None, None, None
        email = user.user_info.email if user.user_info else None
        mobile = user.user_info.mobile_no if user.user_info else None
        return user, user.user_id, email, mobile
    else:
        admin = await resolve_admin(db, identifier)
        if not admin:
            return None, None, None, None
        return admin, admin.admin_user_id, admin.email, admin.mobile_no
