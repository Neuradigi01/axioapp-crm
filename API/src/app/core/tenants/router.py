"""Tenants HTTP routes — ownership transfer (more endpoints may join).

The transfer endpoint is intentionally NOT gated by a `users.write`
permission key: only the org's Owner can fire it (enforced in the
service layer by checking the caller's role row, not a permission
grant).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user
from src.app.core.tenants.ownership import transfer_ownership
from src.app.core.tenants.schemas import (
    OrganizationMemberOut,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/ownership", tags=["Ownership"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/transfer",
    response_model=OwnershipTransferResponse,
    status_code=status.HTTP_200_OK,
)
async def transfer_endpoint(
    payload: OwnershipTransferRequest,
    request: Request,
    caller: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OwnershipTransferResponse:
    new_owner, demoted = await transfer_ownership(
        session,
        caller=caller,
        target_user_uuid=payload.target_user_id,
        demote_to_role_id=payload.demote_to_role_id,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return OwnershipTransferResponse(
        new_owner=OrganizationMemberOut.model_validate(new_owner),
        demoted=OrganizationMemberOut.model_validate(demoted),
    )
