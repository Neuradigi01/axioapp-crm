from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import LoginRequest
from src.services.auth import login_service
from src.utilities.app_utils import extract_login_context

router = APIRouter()


@router.post('/login')
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = await extract_login_context(request, req.device_info)
    return await login_service.authenticate_user(
        db=db,
        identifier=req.identifier,
        password=req.password,
        two_factor_code=req.two_factor_code,
        two_factor_method=req.two_factor_method,
        captcha_token=req.captcha_token,
        captcha_answer=req.captcha_answer,
        **ctx,
    )


@router.post('/admin-login')
async def admin_login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = await extract_login_context(request, req.device_info)
    return await login_service.authenticate_admin(
        db=db,
        identifier=req.identifier,
        password=req.password,
        two_factor_code=req.two_factor_code,
        two_factor_method=req.two_factor_method,
        captcha_token=req.captcha_token,
        captcha_answer=req.captcha_answer,
        **ctx,
    )
