from sqlalchemy.ext.asyncio import AsyncSession

from config import PUSH_NOTIFICATION_ENABLED
from src.constants import messages
from src.data_access import device_token_da
from src.data_access.resolution_da import resolve_member_id
from src.schemas.device_token import RegisterTokenRequest


async def register_device_token(
    db: AsyncSession,
    user_id: str,
    user_type: str,
    payload: RegisterTokenRequest,
) -> dict:
    if not PUSH_NOTIFICATION_ENABLED:
        return {"success": True, "message": messages.OK}

    member_id = await resolve_member_id(db, user_id, user_type)
    if not member_id:
        return {"success": False, "message": messages.RECORD_NOT_FOUND}

    await device_token_da.register_token(
        db,
        member_id=member_id,
        user_type=user_type,
        fcm_token=payload.fcm_token,
        device_info=payload.device_info,
    )
    await db.commit()
    return {"success": True, "message": messages.OK}


async def unregister_device_token(db: AsyncSession, fcm_token: str) -> dict:
    if not PUSH_NOTIFICATION_ENABLED:
        return {"success": True, "message": messages.OK}

    await device_token_da.unregister_token(db, fcm_token)
    await db.commit()
    return {"success": True, "message": messages.OK}
