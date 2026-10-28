from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.password import service as password_service
from src.app.shared.db import get_db

router = APIRouter(tags=["Auth — Password"])


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., min_length=1)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class PasswordResetMessage(BaseModel):
    message: str


@router.post("/forgot-password", response_model=PasswordResetMessage)
async def forgot_password(
    req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> PasswordResetMessage:
    await password_service.request_reset(db, req.identifier)
    return PasswordResetMessage(
        message="If an account exists for that identifier, a reset link has been sent."
    )


@router.post("/reset-password", response_model=PasswordResetMessage)
async def reset_password(
    req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> PasswordResetMessage:
    if not await password_service.reset_password(db, req.token, req.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return PasswordResetMessage(message="Password updated. You can now log in.")
