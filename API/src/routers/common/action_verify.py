from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.route_ids import RouteIds
from src.core.db import get_db
from src.core.security.access_guard import AccessGuard
from src.schemas.action_verify import SendActionVerifyOtpRequest, VerifyActionRequest
from src.services import common_service
from src.services.security import action_verify_service

router = APIRouter(prefix="/action-verify")


@router.post("/send-otp")
async def send_action_verify_otp(
    req: SendActionVerifyOtpRequest,
    token_payload: dict = Depends(AccessGuard([RouteIds.USER_PROFILE, RouteIds.ADMIN_PROFILE])),
    db: AsyncSession = Depends(get_db),
):
    return await common_service.send_otp_to_member(
        db,
        user_id=token_payload["user_id"],
        user_type=token_payload["role"],
        method=req.method,
        purpose="action_verify",
        require_2fa_enabled=True,
    )


@router.post("")
async def verify_action(
    req: VerifyActionRequest,
    token_payload: dict = Depends(AccessGuard([RouteIds.USER_PROFILE, RouteIds.ADMIN_PROFILE])),
    db: AsyncSession = Depends(get_db),
):
    return await action_verify_service.verify_action(
        db,
        user_id=token_payload["user_id"],
        user_type=token_payload["role"],
        code=req.code,
        method=req.method,
    )
