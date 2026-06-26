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

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.gmail.router import router as gmail_router
from src.app.core.email.microsoft.router import router as microsoft_router
from src.app.core.email.schemas import EmailAccountRead
from src.app.core.email.service import (
    disconnect_as_caller,
    list_accounts_visible_to,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/email", tags=["Email Accounts"])

# Gmail sub-router (Step 2) — full paths become
# `/api/v1/email/gmail/authorize | /callback | /push`. Importing
# `gmail.router` chains through `gmail.__init__` which registers
# `GmailProvider` into the OAuth registry — so the registration
# happens before any request hits.
router.include_router(gmail_router)
# Microsoft Graph sub-router (Step 3) — full paths become
# `/api/v1/email/microsoft/authorize | /callback | /webhook`.
# Same side-effect chain as Gmail: importing `microsoft.router`
# triggers `microsoft.__init__` which registers `MicrosoftProvider`.
router.include_router(microsoft_router)


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
    rows = await list_accounts_visible_to(db, caller=user)
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
    await disconnect_as_caller(db, caller=user, account_id=account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
