from sqlalchemy.ext.asyncio import AsyncSession
from src.services.common_service import get_member_with_contact_info, verify_2fa_code
from src.core.security.action_token import create_action_token
from src.constants import messages


async def verify_action(db: AsyncSession, user_id: str, user_type: str, code: str, method: str) -> dict:
    record, _, _ = await get_member_with_contact_info(db, user_id, user_type)
    if not record:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    if not record.two_factor_enabled:
        return {"success": False, "message": messages.TWO_FACTOR_NOT_ENABLED}

    verified = await verify_2fa_code(db, record.id, record, method, code, "action_verify")
    if not verified:
        return {"success": False, "message": messages.INVALID_OTP}

    token, jti, expires_at = create_action_token(user_id, user_type)

    await db.commit()

    return {
        "success": True,
        "message": messages.ACTION_VERIFIED,
        "data": {"action_token": token},
    }
