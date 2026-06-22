from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import service as auth_service
from src.app.core.auth.schemas import TryAnotherWayRequest, TryAnotherWayResponse
from src.app.core.auth.two_factor import service as two_factor_service
from src.app.shared.db import get_db
from src.app.shared.security.password import verify_password

router = APIRouter(prefix="/2fa", tags=["Auth — Two Factor"])


@router.post("/try-another-way", response_model=TryAnotherWayResponse)
async def try_another_way(
    req: TryAnotherWayRequest, db: AsyncSession = Depends(get_db)
) -> TryAnotherWayResponse:
    """Switch the 2FA delivery method mid-login.

    The user has hit `/login` once, received a `TwoFactorChallengeResponse`,
    and now wants the OTP delivered via a different method (e.g. email
    instead of SMS). We re-verify credentials before dispatching the new
    OTP so this endpoint can't be used as an OTP-blasting oracle.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
    )

    if req.org_slug:
        org = await auth_service._get_org_by_slug(db, req.org_slug)
    else:
        org = await auth_service._resolve_org_for_email(db, req.email)
    if org is None:
        raise invalid

    user = await auth_service._get_user_by_email_in_org(db, org.id, req.email)
    if user is None or not user.is_active:
        raise invalid
    if not verify_password(req.password, user.password_hash):
        raise invalid

    result = await two_factor_service.switch_method(
        db,
        member_id=user.id,
        email=user.info.email if user.info else None,
        mobile=user.info.mobile_no if user.info else None,
        method=req.method,
    )
    return TryAnotherWayResponse(
        method=result.method, available_methods=result.available_methods
    )
