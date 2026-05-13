"""HTTP routes for the staff-portal auth surface.

  GET  /api/v1/staff-portal/users?org_slug=demo   → picker rows
  POST /api/v1/staff-portal/auth/login            → {staff_token, expires_at}

Both endpoints are unauthenticated by design — the staff tablet
doesn't have a JWT yet at login time. Tenant context is resolved
explicitly from `org_slug`. Authenticated staff-portal endpoints in
later steps depend on `get_current_staff` from `auth.dependencies`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.staff_portal.schemas import (
    StaffLoginPayload,
    StaffLoginResponse,
    StaffPickerUser,
)
from src.app.core.staff_portal.service import list_pickable_users, login
from src.app.shared.db import get_db


router = APIRouter(prefix="/staff-portal", tags=["StaffPortal"])


@router.get("/users", response_model=list[StaffPickerUser])
async def list_pickable_users_endpoint(
    org_slug: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> list[StaffPickerUser]:
    return await list_pickable_users(db, org_slug=org_slug)


@router.post(
    "/auth/login",
    response_model=StaffLoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login_endpoint(
    payload: StaffLoginPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StaffLoginResponse:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    result = await login(
        db,
        org_slug=payload.org_slug,
        user_id=payload.user_id,
        pin=payload.pin,
        ip=ip,
        ua=ua,
    )
    return StaffLoginResponse.model_validate(result)
