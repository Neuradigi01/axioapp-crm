"""Meta provider-specific HTTP routes.

  GET  /api/v1/integrations/meta/authorize              → 302 to Facebook consent
  GET  /api/v1/integrations/meta/callback?code=&state=  → exchange + persist
  GET  /api/v1/integrations/meta/pages                  → admin: managed Pages
  GET  /api/v1/integrations/meta/pages/{id}/forms       → admin: Lead Forms on a Page
  POST /api/v1/integrations/meta/pages/{id}/subscribe   → admin: subscribe to leadgen
  POST /api/v1/integrations/meta/pages/{id}/unsubscribe → admin: stop deliveries

Authorize + the admin endpoints sit behind `settings.integrations.manage`.
Callback is HIT BY FACEBOOK'S BROWSER, so it can't gate on the CRM
JWT — HMAC-signed `state` is the trust root.

Same shape as `google/router.py` — symmetric on purpose so the Step-7
Settings UI can drive both providers through a common shape.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import FRONTEND_URL
from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.meta import oauth, subscriptions
from src.app.core.integrations.meta.api_client import (
    MetaGraphClient,
    MetaTokenExpiredError,
)
from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.service import get as get_integration
from src.app.core.users.models import User
from src.app.shared.context import (
    RequestContext,
    reset_context,
    set_context,
)
from src.app.shared.db import async_session, get_db


router = APIRouter(prefix="/meta", tags=["Ad Integrations — Meta"])


# Where the OAuth dance bounces back. Settings page reads `?status=…`
# and shows the matching toast — same query-string vocabulary as the
# Google callback so the frontend toast logic is shared.
_SETTINGS_RETURN_PATH = "/user/settings/integrations"


@router.get("/authorize")
async def authorize_endpoint(
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> RedirectResponse:
    """Build the Facebook consent URL + 302. State encodes the active
    tenant + actor so the callback can re-establish scope without a
    JWT (callback comes from Facebook's browser, not our frontend)."""
    url = oauth.start_authorize(
        org_id=user.org_id, actor_id=user.legacy_uuid
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", include_in_schema=False)
async def callback_endpoint(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_reason: str = Query(default=""),
) -> RedirectResponse:
    """Facebook's redirect target after consent. Verifies state, runs
    the short→long token exchange, persists, then bounces back to the
    Settings page with a status param.

    NO permission gate — Facebook's browser hits this URL, not the
    CRM's frontend. The HMAC-signed `state` is the trust root.

    We don't use `Depends(get_db)` here: the request arrives with no
    JWT so middleware leaves `RequestContext.org_id=None`, and a
    session opened that way would never set `app.org_id` for RLS. We
    decode state first, push the org into the request context, THEN
    open a session — same pattern as `google/router.py` + `embed/
    submissions.py`.
    """
    if error:
        # User clicked Cancel / Facebook rejected the redirect_uri.
        # `error_reason` is more user-friendly than `error` for the toast.
        reason = error_reason or error
        return _settings_redirect(status_param="meta_denied", reason=reason)
    if not code or not state:
        return _settings_redirect(
            status_param="meta_error", reason="missing_params"
        )

    try:
        payload = oauth.verify_state(state)
        org_id = uuid.UUID(payload["org_id"])
    except HTTPException:
        return _settings_redirect(
            status_param="meta_error", reason="invalid_state"
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
                    status_param="meta_error",
                    reason="token_exchange_failed",
                )
            except Exception as exc:
                return _settings_redirect(
                    status_param="meta_error",
                    reason=type(exc).__name__,
                )
    finally:
        reset_context(ctx_token)
    return _settings_redirect(status_param="meta_connected")


# --- Pages + Forms --------------------------------------------------------


@router.get("/pages")
async def list_pages_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> list[dict]:
    """List every Facebook Page the OAuth user manages. Settings UI
    drives the per-Page subscribe picker off this. Returns `[]` (not
    404) when Meta isn't connected yet — keeps the picker UI simple."""
    integration = await get_integration(
        db, provider=IntegrationProvider.meta_ads
    )
    if integration is None:
        return []
    client = MetaGraphClient(integration=integration, session=db)
    try:
        pages = await subscriptions.list_pages(client)
    except MetaTokenExpiredError:
        # Surface as 401 so the UI can map to a "reconnect" CTA. The
        # api_client already flipped status to `expired` and committed.
        raise HTTPException(
            status_code=401,
            detail="Meta token expired — reconnect required.",
        )
    return [
        {
            "page_id": p.page_id,
            "name": p.name,
            "category": p.category,
            # NEVER expose page tokens via the API — they're as
            # sensitive as the user token. The subscribe/unsubscribe
            # endpoints re-fetch internally.
        }
        for p in pages
    ]


@router.get("/pages/{page_id}/forms")
async def list_lead_forms_endpoint(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> list[dict]:
    """List Lead Forms on a Page. Internally re-fetches Pages to
    locate the per-Page access_token (we deliberately don't persist
    Page tokens in v1)."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        page_token = await subscriptions.find_page_token(
            client, page_id=page_id
        )
        if not page_token:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_id} not managed by the connected Meta user.",
            )
        forms = await subscriptions.list_lead_forms_for_page(
            client, page_id=page_id, page_token=page_token
        )
    except MetaTokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail="Meta token expired — reconnect required.",
        )
    return [
        {"form_id": f.form_id, "name": f.name, "status": f.status}
        for f in forms
    ]


@router.post("/pages/{page_id}/subscribe")
async def subscribe_page_endpoint(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> dict:
    """Subscribe to the `leadgen` field on this Page. After 200, Meta
    starts delivering lead events to our webhook URL (configured ONCE
    per environment in the Meta app dashboard — Step 5)."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        page_token = await subscriptions.find_page_token(
            client, page_id=page_id
        )
        if not page_token:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_id} not managed by the connected Meta user.",
            )
        ok = await subscriptions.subscribe_page(
            client, page_id=page_id, page_token=page_token
        )
    except MetaTokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail="Meta token expired — reconnect required.",
        )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Meta did not confirm the subscription.",
        )
    return {"status": "subscribed", "page_id": page_id}


@router.post("/pages/{page_id}/unsubscribe")
async def unsubscribe_page_endpoint(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> dict:
    """Stop `leadgen` deliveries for this Page. Doesn't touch other
    Pages on the same integration."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        page_token = await subscriptions.find_page_token(
            client, page_id=page_id
        )
        if not page_token:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_id} not managed by the connected Meta user.",
            )
        ok = await subscriptions.unsubscribe_page(
            client, page_id=page_id, page_token=page_token
        )
    except MetaTokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail="Meta token expired — reconnect required.",
        )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Meta did not confirm the unsubscription.",
        )
    return {"status": "unsubscribed", "page_id": page_id}


# --- helpers -------------------------------------------------------------


async def _require_meta(db: AsyncSession):
    """Return the connected Meta integration row for the active tenant
    or 404. Used by every endpoint that needs to make a Graph API call."""
    integration = await get_integration(
        db, provider=IntegrationProvider.meta_ads
    )
    if integration is None:
        raise HTTPException(
            status_code=404,
            detail="No Meta Ads integration for this org. Connect first.",
        )
    return integration


def _settings_redirect(
    *, status_param: str, reason: str | None = None
) -> RedirectResponse:
    """Bounce back to Settings with `?status=…&reason=…`. Same query
    vocab as the Google callback so the frontend toast logic is shared."""
    from urllib.parse import urlencode

    params: dict[str, str] = {"status": status_param}
    if reason:
        params["reason"] = reason
    return RedirectResponse(
        url=f"{FRONTEND_URL}{_SETTINGS_RETURN_PATH}?{urlencode(params)}",
        status_code=302,
    )


__all__ = ["router"]
