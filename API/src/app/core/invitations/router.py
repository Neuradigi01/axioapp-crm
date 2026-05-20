"""HTTP routes for the invitations module.

Five endpoints:

  POST   /api/v1/invitations             admin issues an invitation
  GET    /api/v1/invitations             admin lists pending invitations
  DELETE /api/v1/invitations/{id}        admin revokes a pending invitation
  GET    /api/v1/invitations/lookup      unauthenticated — accept-page preview
  POST   /api/v1/invitations/accept      unauthenticated — redeem + auto-login
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from config import FRONTEND_URL
from src.app.core.auth.dependencies import require_permissions
from src.app.core.auth.schemas import LoginResponse
from src.app.core.invitations.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationLookup,
    InvitationOut,
)
from src.app.core.invitations.service import (
    accept_invitation,
    create_invitation,
    list_pending,
    lookup_invitation,
    revoke_invitation,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/invitations", tags=["Invitations"])


@router.post(
    "",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    payload: InvitationCreate,
    request: Request,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> InvitationCreated:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    inv, accept_link = await create_invitation(
        session,
        org_id=user.org_id,
        invited_by=user.legacy_uuid,
        payload=payload,
        frontend_url=FRONTEND_URL,
        ip=ip,
        ua=ua,
    )
    base = InvitationOut.model_validate(inv).model_dump()
    base["accept_link"] = accept_link
    return InvitationCreated.model_validate(base)


@router.get("", response_model=list[InvitationOut])
async def list_endpoint(
    user: User = Depends(require_permissions("users.read")),
    session: AsyncSession = Depends(get_db),
) -> list[InvitationOut]:
    rows = await list_pending(session, org_id=user.org_id)
    return [InvitationOut.model_validate(r) for r in rows]


@router.delete(
    "/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_endpoint(
    invitation_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permissions("users.write")),
    session: AsyncSession = Depends(get_db),
) -> Response:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await revoke_invitation(
        session,
        invitation_id=invitation_id,
        org_id=user.org_id,
        revoked_by=user.legacy_uuid,
        ip=ip,
        ua=ua,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- unauthenticated surface (the recipient flow) ------------------------


@router.get("/lookup", response_model=InvitationLookup)
async def lookup_endpoint(
    token: str = Query(min_length=8, max_length=255),
    session: AsyncSession = Depends(get_db),
) -> InvitationLookup:
    info = await lookup_invitation(session, raw_token=token)
    return InvitationLookup.model_validate(info)


@router.post("/accept", response_model=LoginResponse)
async def accept_endpoint(
    payload: InvitationAccept,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> LoginResponse:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    result = await accept_invitation(
        session, payload=payload, ip=ip, ua=ua
    )
    return LoginResponse.model_validate(result)
