from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.core.security.access_guard import AccessGuard
from src.core.security.action_token import ActionTokenGuard
from src.schemas.two_factor import SendSetupOtpRequest, VerifyAndEnableRequest, ChangeMethodRequest
from src.services.security import two_factor_service
from src.services import common_service
from src.constants.route_ids import RouteIds

router = APIRouter(
    prefix="/2fa",
    tags=["Two Factor"],
)

_guard = AccessGuard([RouteIds.USER_SECURITY, RouteIds.ADMIN_SECURITY])


@router.get('/status')
async def get_status(
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await two_factor_service.get_2fa_status(db, user_id=token_payload["user_id"], user_type=token_payload["role"])


@router.post('/setup-authenticator')
async def setup_authenticator(
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await two_factor_service.setup_2fa_authenticator(db, user_id=token_payload["user_id"], user_type=token_payload["role"])


@router.post('/send-setup-otp')
async def send_setup_otp(
    req: SendSetupOtpRequest,
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await common_service.send_otp_to_member(db, user_id=token_payload["user_id"], user_type=token_payload["role"], method=req.method, purpose="2fa_setup")


@router.post('/verify-and-enable')
async def verify_and_enable(
    req: VerifyAndEnableRequest,
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await two_factor_service.verify_and_enable_2fa(db, user_id=token_payload["user_id"], user_type=token_payload["role"], code=req.code, method=req.method)


@router.post('/disable', dependencies=[Depends(ActionTokenGuard())])
async def disable(
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await two_factor_service.disable_2fa(db, user_id=token_payload["user_id"], user_type=token_payload["role"])


@router.post('/change-method', dependencies=[Depends(ActionTokenGuard())])
async def change_method(
    req: ChangeMethodRequest,
    token_payload: dict = Depends(_guard),
    db: AsyncSession = Depends(get_db),
):
    return await two_factor_service.change_2fa_method(db, user_id=token_payload["user_id"], user_type=token_payload["role"], new_method=req.new_method)
