from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.access_guard import AccessGuard
from src.schemas.common import ChangePasswordRequest
from src.services import common_service
from src.constants.route_ids import RouteIds

router = APIRouter()


@router.post('/change-password')
async def change_password(
    req: ChangePasswordRequest,
    token_payload: dict = Depends(AccessGuard([RouteIds.USER_CHANGE_PASSWORD, RouteIds.ADMIN_CHANGE_PASSWORD])),
    db: AsyncSession = Depends(get_db),
):
    return await common_service.change_password(db, user_id=token_payload["user_id"], user_type=token_payload["role"], req=req)
