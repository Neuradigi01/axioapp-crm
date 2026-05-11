from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import ForgotPasswordRequest
from src.services.auth import password_reset_service

router = APIRouter()


@router.post('/forgot-password')
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    return await password_reset_service.request_password_reset(db=db, identifier=req.identifier)
