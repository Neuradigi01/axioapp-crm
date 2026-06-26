from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants import service as tenants_service
from src.app.core.users import service as users_service
from src.app.core.auth import service as auth_service
from src.app.core.auth.schemas import TryAnotherWayRequest, TryAnotherWayResponse
from src.app.core.auth.two_factor import service as two_factor_service
from src.app.shared.db import get_db
from src.app.shared.security.password import verify_password
from src.services.auth import login_service

router = APIRouter(prefix="/2fa", tags=["Auth — Two Factor"])


@router.post("/try-another-way", response_model=TryAnotherWayResponse)
async def try_another_way(
    req: TryAnotherWayRequest, db: AsyncSession = Depends(get_db)
) -> TryAnotherWayResponse:
    """Switch the 2FA delivery method mid-login.

    Supports both pools:
      * `user_type="User"` — FurnitureCRM layered user (default).
      * `user_type="Admin"` — legacy template admin pool. Delegated to
        `login_service.try_another_way` because admin lives on
        `tbl_admin` with the legacy `access_rights`/JWT shape.
    """
    if req.user_type == "Admin":
        legacy_identifier = req.identifier or req.email
        if not legacy_identifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Identifier is required",
            )
        result = await login_service.try_another_way(
            db,
            identifier=legacy_identifier,
            password=req.password,
            user_type="Admin",
            method=req.method,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("message", "Could not switch method"),
            )
        data = result.get("data") or {}
        return TryAnotherWayResponse(
            method=data.get("method", req.method),
            available_methods=data.get("available_methods", []),
        )

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
    )
    user_email = req.email or req.identifier
    if not user_email:
        raise invalid

    if req.org_slug:
        org = await tenants_service.get_organization_by_slug(db, req.org_slug)
    else:
        org = await auth_service.resolve_org_for_email(db, user_email)
    if org is None:
        raise invalid

    user = await users_service.get_user_by_email(
        db, user_email, org_id=org.id, active_only=True
    )
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
