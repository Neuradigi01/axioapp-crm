from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import TwoFactorRequest
from src.services.auth import login_service

router = APIRouter()


@router.post('/2fa-try-another-way')
async def try_another_way(req: TwoFactorRequest, db: AsyncSession = Depends(get_db)):
    return await login_service.try_another_way(
        db,
        identifier=req.identifier,
        password=req.password,
        user_type=req.user_type,
        method=req.method,
    )
