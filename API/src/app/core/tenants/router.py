"""Tenants HTTP routes — ownership transfer + send-rule settings.

The transfer endpoint is intentionally NOT gated by a `users.write`
permission key: only the org's Owner can fire it (enforced in the
service layer by checking the caller's role row, not a permission
grant).

The Step-13 send-rules GET/PATCH endpoints surface the quiet-hours
+ frequency-cap controls the send-guard layer uses to gate
marketing-category automation runs. Gated on `settings.write` —
same key the rest of the org-wide Settings PATCH endpoints honour.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import get_current_user, require_permissions
from src.app.core.tenants.models import Organization
from src.app.core.tenants.ownership import transfer_ownership
from src.app.core.tenants.schemas import (
    OrganizationMemberOut,
    OwnershipTransferRequest,
    OwnershipTransferResponse,
    SendRulesOut,
    SendRulesUpdate,
)
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db


router = APIRouter(prefix="/ownership", tags=["Ownership"])
send_rules_router = APIRouter(prefix="/tenants", tags=["Tenants"])


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


# --- Step-13 send-rule endpoints ----------------------------------------


async def _load_active_org(session: AsyncSession) -> Organization:
    """Resolve the active request's Organization row off the request
    context. Raises 400 if the request landed without an org context
    (shouldn't happen behind ``require_permissions`` but defends
    against the corner case)."""
    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )
    org = (
        await session.execute(
            select(Organization).where(Organization.id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organisation not found",
        )
    return org


@send_rules_router.get(
    "/send-rules",
    response_model=SendRulesOut,
    status_code=status.HTTP_200_OK,
)
async def get_send_rules(
    _: User = Depends(require_permissions("settings.write")),
    session: AsyncSession = Depends(get_db),
) -> SendRulesOut:
    """Read the current org's send-guard compliance settings (quiet
    hours + frequency cap). Drives the Settings → Send rules tab."""
    org = await _load_active_org(session)
    return SendRulesOut.model_validate(org)


@send_rules_router.patch(
    "/send-rules",
    response_model=SendRulesOut,
    status_code=status.HTTP_200_OK,
)
async def patch_send_rules(
    payload: SendRulesUpdate,
    _: User = Depends(require_permissions("settings.write")),
    session: AsyncSession = Depends(get_db),
) -> SendRulesOut:
    """Update the send-guard compliance settings. Validates the
    quiet-hours window (wrap-midnight is allowed; ``start == end``
    means "no quiet hours at all" and is permitted)."""
    org = await _load_active_org(session)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(org, key, value)
    await session.commit()
    await session.refresh(org)
    return SendRulesOut.model_validate(org)
