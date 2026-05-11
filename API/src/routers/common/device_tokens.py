from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.access_guard import AccessGuard
from src.schemas.device_token import RegisterTokenRequest, UnregisterTokenRequest
from src.services import device_token_service
from src.constants.route_ids import RouteIds

router = APIRouter(prefix="/device-tokens")


@router.post('/register')
async def register_token(
    req: RegisterTokenRequest,
    token_payload: dict = Depends(AccessGuard([
        RouteIds.USER_NOTIFICATIONS,
        RouteIds.ADMIN_NOTIFICATIONS,
    ])),
    db: AsyncSession = Depends(get_db),
):
    return await device_token_service.register_device_token(
        db,
        user_id=token_payload["user_id"],
        user_type=token_payload["role"],
        payload=req,
    )


@router.post('/unregister')
async def unregister_token(
    req: UnregisterTokenRequest,
    token_payload: dict = Depends(AccessGuard([
        RouteIds.USER_NOTIFICATIONS,
        RouteIds.ADMIN_NOTIFICATIONS,
    ])),
    db: AsyncSession = Depends(get_db),
):
    return await device_token_service.unregister_device_token(db, req.fcm_token)
