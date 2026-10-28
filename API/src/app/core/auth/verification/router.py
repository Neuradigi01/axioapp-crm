from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.verification import service as verification_service
from src.app.core.auth.verification.service import VerificationError
from src.app.shared.db import get_db

router = APIRouter(prefix="/verify-contact", tags=["Auth — Verify Contact"])


class SendContactOtpRequest(BaseModel):
    type: verification_service.ContactType
    value: str = Field(min_length=1, max_length=320)


class SendContactOtpResponse(BaseModel):
    otp_token: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class VerifyEmailResponse(BaseModel):
    message: str


@router.post("/send-otp", response_model=SendContactOtpResponse)
async def send_otp(req: SendContactOtpRequest) -> SendContactOtpResponse:
    try:
        result = await verification_service.send_contact_otp(contact_type=req.type, value=req.value)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return SendContactOtpResponse(otp_token=result.otp_token)


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)
) -> VerifyEmailResponse:
    try:
        await verification_service.verify_email_token(db, req.token)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return VerifyEmailResponse(message="Email verified successfully")
