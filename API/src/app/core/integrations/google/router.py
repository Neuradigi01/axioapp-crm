"""Google Ads provider-specific HTTP routes.

  GET  /api/v1/integrations/google/authorize                   → 302 to Google consent
  GET  /api/v1/integrations/google/callback?code=&state=       → exchange + persist
  GET  /api/v1/integrations/google/accounts                    → admin: accessible ad accounts
  GET  /api/v1/integrations/google/accounts/{cid}/forms        → admin: Lead Forms on cid

Authorize + the admin endpoints sit behind `settings.integrations.manage`.
The callback is HIT BY GOOGLE'S BROWSER and therefore can't gate on
the CRM JWT — the OAuth `state` parameter is what proves it's a
legitimate callback for a known org (HMAC-signed, 10-min TTL,
verified in `oauth.handle_callback`).

The callback redirects to the frontend with a status param so the
Settings page can show "Connected!" or "Couldn't connect: <reason>".
"""
from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import FRONTEND_URL
from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.google import oauth, sync_forms
from src.app.core.integrations.google.api_client import GoogleAdsRestClient
from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.service import get as get_integration
from src.app.core.users.models import User
from src.app.shared.context import (
    RequestContext,
    reset_context,
    set_context,
)
from src.app.shared.db import async_session, get_db


# Prefix is `/google` because this subrouter is included under the
# parent `/integrations` router. Full path becomes
# `/api/v1/integrations/google/...` (the outer `/api/v1` is added by
# main.py when the parent router is mounted).
router = APIRouter(prefix="/google", tags=["Ad Integrations — Google"])


# Where the OAuth dance returns the visitor. The Settings page reads
# `?status=...` and shows the matching toast.
_SETTINGS_RETURN_PATH = "/user/settings/integrations"


@router.get("/authorize")
async def authorize_endpoint(
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> RedirectResponse:
    """Build the Google consent URL + 302 to it. The OAuth `state`
    encodes the active tenant + actor so the callback knows who to
    upsert against (callback can't read the CRM JWT — it's invoked by
    Google's browser, not the in-app frontend)."""
    url = oauth.start_authorize(
        org_id=user.org_id, actor_id=user.legacy_uuid
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", include_in_schema=False)
async def callback_endpoint(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    """Google's redirect target after consent. Verifies state, swaps
    `code` for tokens, encrypts + persists, then bounces back to the
    Settings page with a status param.

    Note: NO permission gate here — Google's browser hits this URL,
    not the CRM's frontend. The HMAC-signed `state` is the trust root.

    We do NOT use `Depends(get_db)` here: the request arrives with no
    JWT, so the middleware leaves `RequestContext.org_id=None`, and a
    session opened that way would never set `app.org_id` for RLS. We
    decode state first, push the org into the request context, THEN
    open a session — same pattern as `core.embed.submissions`.
    """
    if error:
        # User clicked Deny on Google's consent screen — bounce back
        # with the reason so the Settings page can show a friendly
        # message instead of a generic failure.
        return _settings_redirect(status="google_denied", reason=error)
    if not code or not state:
        return _settings_redirect(
            status="google_error", reason="missing_params"
        )

    # Verify state (cheap, no I/O) BEFORE touching the DB. Lets us
    # bail out on forged/expired callbacks without opening a session.
    try:
        payload = oauth.verify_state(state)
        org_id = uuid.UUID(payload["org_id"])
    except HTTPException:
        return _settings_redirect(
            status="google_error", reason="invalid_state"
        )

    ctx_token = set_context(
        RequestContext(org_id=org_id, user_id=None)
    )
    try:
        async with async_session() as session:
            try:
                await oauth.handle_callback(
                    session, code=code, state=state
                )
            except HTTPException:
                return _settings_redirect(
                    status="google_error", reason="token_exchange_failed"
                )
            except Exception as exc:
                return _settings_redirect(
                    status="google_error", reason=type(exc).__name__
                )
    finally:
        reset_context(ctx_token)
    return _settings_redirect(status="google_connected")


def _settings_redirect(
    *, status: str, reason: str | None = None
) -> RedirectResponse:
    """Bounce back to the Settings page with `?status=…` (and an
    optional `&reason=…`). URL-encodes both so a reason carrying
    spaces / unicode lands cleanly in the address bar."""
    params: dict[str, str] = {"status": status}
    if reason:
        params["reason"] = reason
    return RedirectResponse(
        url=f"{FRONTEND_URL}{_SETTINGS_RETURN_PATH}?{urlencode(params)}",
        status_code=302,
    )


@router.get("/accounts")
async def list_accounts_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> list[dict]:
    """List the Google Ads accounts the connected identity can see.
    Returns `[{customer_id, resource_name}]`. The Settings UI in
    Step 7 uses this to drive the "pick which account" panel."""
    integration = await get_integration(
        db, provider=IntegrationProvider.google_ads
    )
    if integration is None:
        return []
    client = GoogleAdsRestClient(integration=integration, session=db)
    accounts = await sync_forms.list_accessible_accounts(client)
    return [
        {
            "customer_id": a.customer_id,
            "resource_name": a.resource_name,
        }
        for a in accounts
    ]


@router.get("/accounts/{customer_id}/forms")
async def list_lead_forms_endpoint(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> list[dict]:
    """List Lead Form assets on the given customer. `customer_id` may
    include hyphens (e.g. "123-456-7890") — we strip them before the
    API call."""
    integration = await get_integration(
        db, provider=IntegrationProvider.google_ads
    )
    if integration is None:
        return []
    client = GoogleAdsRestClient(integration=integration, session=db)
    forms = await sync_forms.list_lead_forms(
        client, customer_id=customer_id.replace("-", "")
    )
    return [
        {
            "form_id": f.form_id,
            "name": f.name,
            "resource_name": f.resource_name,
        }
        for f in forms
    ]
