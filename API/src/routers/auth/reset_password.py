from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import ResetPasswordRequest
from src.services.auth import password_reset_service

router = APIRouter()


@router.post('/reset-password')
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    return await password_reset_service.reset_password(db=db, token=req.token, new_password=req.new_password)
