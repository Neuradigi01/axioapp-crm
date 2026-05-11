from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import RegisterRequest
from src.services.auth import registration_service

router = APIRouter()


@router.post('/register')
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    return await registration_service.register_user(db=db, req=req)
