"""HTTP routes for email-account management.

  GET    /api/v1/email/accounts             → list accounts the caller can see
  DELETE /api/v1/email/accounts/{id}        → disconnect (soft, tokens nulled)

Provider-specific `/connect` + `/callback` endpoints land in Step 2
(Gmail) and Step 3 (Microsoft) as sub-routers mounted onto the same
`/email` prefix.

Visibility rules:

  - A rep with `email.accounts.manage` sees and disconnects ONLY
    their own accounts. The list query filters by `user.legacy_uuid`.
  - A user with the broader `email.accounts.admin` (Owner / Admin
    templates) sees every account in the org and can disconnect any.

The two permissions compose: the route declares the lower bar
(`email.accounts.manage`) so any rep can hit it; admin-only behavior
is decided inside the handler by sniffing the granted set.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.schemas import EmailAccountRead
from src.app.core.email.service import (
    disconnect as disconnect_account,
    get_account,
    list_accounts,
)
from src.app.core.permissions.service import list_permissions_for_role
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/email", tags=["Email Accounts"])


async def _has_admin(db: AsyncSession, user: User) -> bool:
    """Does the caller hold the org-wide admin scope?"""
    granted = {
        p.key for p in await list_permissions_for_role(db, user.role_id)
    }
    return "email.accounts.admin" in granted


@router.get("/accounts", response_model=list[EmailAccountRead])
async def list_email_accounts_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> list[EmailAccountRead]:
    """Return the accounts the caller can see.

    - Owner / Admin (with `email.accounts.admin`): every account in
      the org, regardless of which rep connected it.
    - Rep (`email.accounts.manage` only): just their own.
    """
    admin = await _has_admin(db, user)
    user_filter = None if admin else user.legacy_uuid
    rows = await list_accounts(db, user_id=user_filter)
    return [EmailAccountRead.model_validate(r) for r in rows]


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_email_account_endpoint(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Disconnect an account — clears tokens + flips sync_state to
    `disconnected`. Idempotent — re-disconnecting returns 204 with
    no second audit event. 404 if the row doesn't exist or is
    hidden by RLS.

    A rep without `email.accounts.admin` can only disconnect their
    own accounts; trying to disconnect another rep's account 403s.
    """
    row = await get_account(db, account_id=account_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found.",
        )
    admin = await _has_admin(db, user)
    if not admin and row.user_id != user.legacy_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only disconnect your own email accounts.",
        )
    await disconnect_account(
        db, account_id=account_id, actor_id=user.legacy_uuid
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
