from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.db import get_db
from src.schemas.auth import SendContactOtpRequest, VerifyEmailRequest
from src.services.security import verification_service

router = APIRouter(prefix="/verify-contact")


@router.post('/send-otp')
async def send_otp(req: SendContactOtpRequest):
    return await verification_service.send_contact_otp(req=req)


@router.post('/verify-email')
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    return await verification_service.verify_email(db=db, token=req.token)
