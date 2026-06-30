"""Meta provider-specific HTTP routes.

  GET  /api/v1/integrations/meta/authorize              → 302 to Facebook consent
  GET  /api/v1/integrations/meta/callback?code=&state=  → exchange + persist
  GET  /api/v1/integrations/meta/pages                  → admin: managed Pages
  GET  /api/v1/integrations/meta/pages/{id}/forms       → admin: Lead Forms on a Page
  POST /api/v1/integrations/meta/pages/{id}/subscribe   → admin: subscribe to leadgen
  POST /api/v1/integrations/meta/pages/{id}/unsubscribe → admin: stop deliveries
  POST /api/v1/integrations/meta/data-deletion          → Meta-mandated deletion callback (Step 4)
  GET  /api/v1/integrations/meta/data-deletion/status   → public status lookup by confirmation_code

Authorize + the admin endpoints sit behind `settings.integrations.manage`.
Callback is HIT BY FACEBOOK'S BROWSER, so it can't gate on the CRM
JWT — HMAC-signed `state` is the trust root. The data-deletion routes
have no JWT gate either: Meta posts the deletion callback with its
own HMAC, and the status GET is read by the deleted user (who has no
Core CRM account by definition).

Same shape as `google/router.py` — symmetric on purpose so the Step-7
Settings UI can drive both providers through a common shape.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import FRONTEND_URL, META_APP_SECRET
from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.meta import data_deletion, oauth, subscriptions
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
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> dict:
    """Return the Facebook consent URL as JSON. Same reasoning as
    `google/router.authorize_endpoint`: a top-level browser GET to a
    JWT-gated endpoint can't carry the Bearer header, so the SPA
    fetches the URL via XHR (interceptor-injected token) and then
    navigates the browser to it."""
    url = oauth.start_authorize(org_id=user.org_id, actor_id=user.legacy_uuid)
    return {"url": url}


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
        return _settings_redirect(status_param="meta_error", reason="missing_params")

    try:
        payload = oauth.verify_state(state)
        org_id = uuid.UUID(payload["org_id"])
    except HTTPException:
        return _settings_redirect(status_param="meta_error", reason="invalid_state")

    ctx_token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            try:
                await oauth.handle_callback(session, code=code, state=state)
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
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> list[dict]:
    """List every Facebook Page the OAuth user manages. Settings UI
    drives the per-Page subscribe picker off this. Returns `[]` (not
    404) when Meta isn't connected yet — keeps the picker UI simple."""
    integration = await get_integration(db, provider=IntegrationProvider.meta_ads)
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
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> list[dict]:
    """List Lead Forms on a Page. Internally re-fetches Pages to
    locate the per-Page access_token (we deliberately don't persist
    Page tokens in v1)."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        page_token = await subscriptions.find_page_token(client, page_id=page_id)
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
    return [{"form_id": f.form_id, "name": f.name, "status": f.status} for f in forms]


@router.post("/pages/{page_id}/subscribe")
async def subscribe_page_endpoint(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> dict:
    """Subscribe to the `leadgen` field on this Page. After 200, Meta
    starts delivering lead events to our webhook URL (configured ONCE
    per environment in the Meta app dashboard — Step 5)."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        # Pull the full Page record so we can cache its name alongside
        # the token — picker UI shows it without an extra round trip.
        all_pages = await subscriptions.list_pages(client)
        page = next((p for p in all_pages if p.page_id == page_id), None)
        if page is None:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_id} not managed by the connected Meta user.",
            )
        ok = await subscriptions.subscribe_page(
            client, page_id=page_id, page_token=page.access_token
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
    # Cache the Page token so the Step-5 webhook worker can fetch lead
    # details without re-OAuthing. Runs AFTER Meta confirms — we don't
    # cache tokens for un-subscribed Pages.
    await subscriptions.upsert_page_token(
        db,
        org_id=integration.org_id,
        integration_id=integration.id,
        page_id=page_id,
        page_name=page.name,
        page_token=page.access_token,
    )
    return {"status": "subscribed", "page_id": page_id}


@router.post("/pages/{page_id}/unsubscribe")
async def unsubscribe_page_endpoint(
    page_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> dict:
    """Stop `leadgen` deliveries for this Page. Doesn't touch other
    Pages on the same integration. Also drops the cached Page token
    so a leaked DB dump after disconnect can't be used to call the
    Graph API."""
    integration = await _require_meta(db)
    client = MetaGraphClient(integration=integration, session=db)
    try:
        page_token = await subscriptions.find_page_token(client, page_id=page_id)
        if not page_token:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_id} not managed by the connected Meta user.",
            )
        ok = await subscriptions.unsubscribe_page(client, page_id=page_id, page_token=page_token)
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
    # Always-OK to drop the cache (idempotent). Done AFTER Meta
    # confirms so a half-success doesn't leave us with stale state.
    await subscriptions.delete_page_token(db, integration_id=integration.id, page_id=page_id)
    return {"status": "unsubscribed", "page_id": page_id}


# --- Data Deletion Callback (whatsapp-platform-upgrade Step 4) ----------


@router.post("/data-deletion", include_in_schema=False)
async def data_deletion_callback_endpoint(request: Request) -> dict:
    """Meta's mandated Data Deletion Callback. Receives a form-encoded
    ``signed_request`` whenever a Meta user deletes our app from their
    Facebook profile; responds synchronously with the confirmation URL
    the user can poll for status.

    Auth model: the signed_request is the auth mechanism — HMAC-SHA256
    keyed on ``META_APP_SECRET`` is the trust root, same pattern the
    OAuth ``state`` parameter uses on the callback above. No JWT.

    Idempotency: Meta retries on transient failures. We dedupe by
    ``(meta_user_id, issued_at)`` so re-deliveries reuse the existing
    confirmation_code rather than creating ghost rows."""
    form = await request.form()
    signed_request = form.get("signed_request") or ""
    if not META_APP_SECRET:
        # Deploy hasn't configured the App Secret yet; surface as 503
        # rather than silently 400 every callback. Surfaces to ops in
        # the audit log + Meta logs the failure for the next retry.
        raise HTTPException(
            status_code=503,
            detail="Meta App Secret is not configured on this server.",
        )
    try:
        payload = data_deletion.parse_signed_request(signed_request, app_secret=META_APP_SECRET)
    except data_deletion.SignedRequestError as exc:
        # Don't leak the specific reason — single generic 400 message.
        # Specifics live in server logs for diagnosis.
        import logging

        logging.getLogger(__name__).warning(
            "meta_data_deletion: rejected signed_request reason=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=400, detail="invalid signed_request")

    user_id = payload["user_id"]
    issued_at = payload["issued_at"]

    async with async_session() as session:
        existing = await data_deletion.find_existing_request(
            session, meta_user_id=user_id, issued_at_epoch=issued_at
        )
        if existing is not None:
            # Idempotent replay — return the same confirmation URL Meta
            # already showed the user on the first delivery.
            confirmation_code = existing.confirmation_code
        else:
            integrations = await data_deletion.find_integrations_by_meta_user(
                session, meta_user_id=user_id
            )
            request_row = await data_deletion.record_deletion_request(
                session,
                meta_user_id=user_id,
                issued_at_epoch=issued_at,
                affected_org_ids=[i.org_id for i in integrations],
            )
            await session.commit()
            confirmation_code = request_row.confirmation_code

            # Audit log fires once per callback receipt — picks one of
            # the affected orgs as the tenant scope (audit.log requires
            # an org_id). When zero orgs match, no audit row is written
            # by design; the receipt itself is already logged above.
            from src.app.core import audit as _audit

            if integrations:
                await _audit.log(
                    "compliance.meta_data_deletion.received",
                    entity_type="meta_data_deletion_request",
                    entity_id=request_row.id,
                    org_id=integrations[0].org_id,
                    after={
                        "confirmation_code": confirmation_code,
                        "affected_org_count": len(integrations),
                    },
                )

            # Hand the heavy lifting to Celery; the callback returns to
            # Meta before the scrub finishes. The status endpoint shows
            # progress until the worker flips the row to `completed`.
            from src.app.core.integrations.meta import tasks as _tasks

            _tasks.delete_meta_user_data_async_task.delay(str(request_row.id))

    return {
        "url": (f"{FRONTEND_URL}/data-deletion-status?confirmation_code={confirmation_code}"),
        "confirmation_code": confirmation_code,
    }


@router.get("/data-deletion/status")
async def data_deletion_status_endpoint(
    confirmation_code: str = Query(min_length=1, max_length=64),
) -> dict:
    """Public status lookup by confirmation_code. Anonymous read — the
    code itself is the capability key (~384 bits of entropy)."""
    async with async_session() as session:
        projection = await data_deletion.get_status_by_code(
            session, confirmation_code=confirmation_code
        )
    if projection is None:
        raise HTTPException(
            status_code=404,
            detail="No deletion request found for this code.",
        )
    return projection


# --- helpers -------------------------------------------------------------


async def _require_meta(db: AsyncSession):
    """Return the connected Meta integration row for the active tenant
    or 404. Used by every endpoint that needs to make a Graph API call."""
    integration = await get_integration(db, provider=IntegrationProvider.meta_ads)
    if integration is None:
        raise HTTPException(
            status_code=404,
            detail="No Meta Ads integration for this org. Connect first.",
        )
    return integration


def _settings_redirect(*, status_param: str, reason: str | None = None) -> RedirectResponse:
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
