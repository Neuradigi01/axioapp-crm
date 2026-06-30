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

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.bounce_handler import (
    UnsupportedWebhookError,
    parse_provider_payload,
    persist_bounce_events,
    verify_mailgun_signature,
)
from src.app.core.email.dkim_spf_check import (
    DomainAuthStatus,
    check_domain,
)
from src.app.core.email.gmail.router import router as gmail_router
from src.app.core.email.microsoft.router import router as microsoft_router
from src.app.core.email.schemas import EmailAccountRead
from src.app.core.email.service import (
    disconnect_as_caller,
    list_accounts_visible_to,
)
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db

logger = logging.getLogger(__name__)


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


# --- Step-14 bounce/complaint webhook endpoints ----------------------------


class BounceWebhookResponse(BaseModel):
    """Lean response shape — providers expect a 200 with any body."""

    recorded: int = Field(default=0)
    suppressed: int = Field(default=0)
    skipped_dupes: int = Field(default=0)


@router.post(
    "/bounce-webhook/{provider}/{org_id}",
    response_model=BounceWebhookResponse,
    status_code=status.HTTP_200_OK,
)
async def bounce_webhook_endpoint(
    provider: str,
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> BounceWebhookResponse:
    """Public, HMAC-validated bounce / complaint webhook intake.

    Mounted at ``/api/v1/email/bounce-webhook/{provider}/{org_id}`` —
    the org_id is in the URL path because the provider's payload
    doesn't carry the CRM's tenant id; the operator configures the
    provider with a per-org URL when wiring the webhook.

    Provider-specific HMAC verification:
      * ``mailgun``: signing key checked against the payload's
        ``signature.timestamp`` + ``signature.token``.
      * ``sendgrid`` / ``ses`` / ``postmark``: v1 accepts the payload
        as-is; production setups front the endpoint with a gateway
        verifier (Cloudflare / API gateway). The shape parser still
        validates fields before persisting.

    The endpoint is read-only of request bodies (no DB writes happen
    before parsing succeeds), so a forged payload that fails to
    parse simply 400s without touching the DB.
    """
    try:
        payload: Any = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_json",
        )

    # Provider-specific HMAC. Mailgun is in-band; the rest are
    # gateway-validated so we accept them by shape.
    if provider.lower() == "mailgun":
        # Signing key lives in env (``MAILGUN_WEBHOOK_SIGNING_KEY``).
        # When unset, we DEFAULT-DENY rather than fail-open: an
        # operator who set up the webhook without configuring the
        # signing key would otherwise accept anything.
        import os

        signing_key = os.environ.get("MAILGUN_WEBHOOK_SIGNING_KEY", "")
        if not signing_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="mailgun_signing_key_not_configured",
            )
        if not isinstance(payload, dict) or not verify_mailgun_signature(
            payload, signing_key=signing_key
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_signature",
            )

    try:
        events = parse_provider_payload(provider, payload)
    except UnsupportedWebhookError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if not events:
        return BounceWebhookResponse()

    # The handler opens its own writes; we feed it the request's
    # session. Cross-tenant context is intentional — the URL's
    # org_id is the authority.
    summary = await persist_bounce_events(db, org_id=org_id, events=events)
    return BounceWebhookResponse(**summary)


# --- Step-14 domain-status endpoint ---------------------------------------


class DomainStatusOut(BaseModel):
    domain: str
    spf: str
    dkim: str
    dmarc: str
    last_checked_at: float


@router.get(
    "/domain-status",
    response_model=DomainStatusOut,
)
async def domain_status_endpoint(
    domain: str,
    force_refresh: bool = False,
    _: User = Depends(require_permissions("email.accounts.manage")),
) -> DomainStatusOut:
    """Resolve + return the SPF / DKIM / DMARC verdict for ``domain``.

    Caches per ``(org_id, domain)`` for 6 hours so the Settings UI
    can poll cheaply. Pass ``force_refresh=true`` to bypass the
    cache (e.g. operator just updated DNS).
    """
    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )

    status_result: DomainAuthStatus = await check_domain(
        org_id=str(ctx.org_id),
        domain=domain,
        force_refresh=force_refresh,
    )
    return DomainStatusOut(
        domain=status_result.domain,
        spf=status_result.spf,
        dkim=status_result.dkim,
        dmarc=status_result.dmarc,
        last_checked_at=status_result.last_checked_at,
    )


# --- Step-14 suppression list endpoints -----------------------------------


class SuppressionRowOut(BaseModel):
    id: uuid.UUID
    channel: str
    address: str
    reason: str
    created_at: str


@router.get(
    "/suppressions",
    response_model=list[SuppressionRowOut],
)
async def list_suppressions_endpoint(
    channel: str | None = None,
    reason: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("email.accounts.manage")),
) -> list[SuppressionRowOut]:
    """Filterable suppression list — drives the Settings → Email
    suppression viewer. Filter by channel + reason; pagination via
    offset/limit."""
    from sqlalchemy import select as _select

    from src.app.core.automation.models import AutomationSuppression

    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )

    stmt = (
        _select(AutomationSuppression)
        .where(AutomationSuppression.org_id == ctx.org_id)
        .order_by(AutomationSuppression.created_at.desc())
        .offset(offset)
        .limit(min(limit, 500))
    )
    if channel is not None:
        stmt = stmt.where(AutomationSuppression.channel == channel)
    if reason is not None:
        stmt = stmt.where(AutomationSuppression.reason == reason)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        SuppressionRowOut(
            id=r.id,
            channel=str(r.channel.value if hasattr(r.channel, "value") else r.channel),
            address=r.address,
            reason=str(r.reason.value if hasattr(r.reason, "value") else r.reason),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.delete(
    "/suppressions/{suppression_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_suppression_endpoint(
    suppression_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Manual rehabilitation — operator removes a row so the next
    send to that address proceeds normally. The
    ``tbl_email_bounce_events`` row stays (audit history). Soft 204
    on a missing id so the action is idempotent across rapid
    double-clicks."""
    from sqlalchemy import select as _select

    from src.app.core.automation.models import AutomationSuppression

    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )

    row = (
        await db.execute(
            _select(AutomationSuppression).where(
                AutomationSuppression.id == suppression_id,
                AutomationSuppression.org_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
