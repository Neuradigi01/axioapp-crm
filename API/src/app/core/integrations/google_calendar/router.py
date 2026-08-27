"""Per-user Google Calendar OAuth HTTP routes.

  GET   /api/v1/integrations/google-calendar/authorize   → JSON `{url}` to Google consent
  GET   /api/v1/integrations/google-calendar/callback    → Google redirects here after consent
  POST  /api/v1/integrations/google-calendar/disconnect  → revoke + delete row
  GET   /api/v1/integrations/google-calendar/status      → connection state for the card

The authorize + disconnect + status endpoints run under the CRM JWT
(any authenticated user can connect / disconnect / read THEIR OWN
calendar connection — no ``settings.integrations.manage`` permission
required, because this isn't an org-wide setting). The callback is
hit by GOOGLE'S BROWSER and cannot gate on the JWT — the state HMAC
+ 10-min TTL are the trust root, matching the Ads flow's convention.
"""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import FRONTEND_URL
from src.app.core.auth.dependencies import get_current_user
from src.app.core.integrations.google_calendar import service as _service
from src.app.core.users.models import User
from src.app.shared.context import (
    RequestContext,
    reset_context,
    set_context,
)
from src.app.shared.db import async_session, get_db


logger = logging.getLogger(__name__)


# Prefix `/google-calendar` — this subrouter is included under the
# parent `/integrations` router. Full path becomes
# `/api/v1/integrations/google-calendar/...`.
router = APIRouter(
    prefix="/google-calendar", tags=["Integrations — Google Calendar"]
)


# Where the OAuth callback redirects the visitor after a success /
# failure. The Integrations page reads ``?status=...`` + shows the
# matching toast.
_INTEGRATIONS_RETURN_PATH = "/user/integrations"


def _resolve_org_id(user: User) -> uuid.UUID:
    """Read the active org_id off the request context. The
    ``get_current_user`` dependency already validated the JWT + pushed
    the tenant into context; the user's own ``.org_id`` is a matching
    denormalised value on the User model."""
    org_id = getattr(user, "org_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current session has no active organisation.",
        )
    return org_id


# --- authorize --------------------------------------------------------


@router.get("/authorize")
async def authorize_endpoint(
    user: User = Depends(get_current_user),
) -> dict:
    """Return Google's consent URL as JSON so the SPA can navigate to
    it. We do NOT 302 here because a top-level browser GET to
    ``/api/v1/...`` doesn't carry the Bearer header (only XHR does),
    so a 302 path would 401 before reaching the redirect.

    Frontend pattern: XHR to this endpoint → receive ``{url}`` →
    ``window.location.assign(url)``.

    The signed ``state`` inside the URL encodes ``(org_id, user_id)``
    so the eventual ``/callback`` (which is unauthenticated — Google's
    browser hits it) can re-establish org context.
    """
    org_id = _resolve_org_id(user)
    url = _service.build_authorize_url(org_id=org_id, user_id=int(user.id))
    return {"url": url}


# --- callback ---------------------------------------------------------


@router.get("/callback", include_in_schema=False)
async def callback_endpoint(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    """Google's redirect target after consent. Verifies state, swaps
    ``code`` for tokens, encrypts + persists, then bounces the browser
    back to the Integrations page with a ``?status=...`` param.

    NO permission gate — Google's browser hits this URL, not the CRM
    frontend. The HMAC-signed ``state`` is the trust root.

    We do NOT use ``Depends(get_db)`` here: the request arrives with
    no JWT, so the middleware leaves ``RequestContext.org_id=None``,
    and a session opened that way would never set ``app.org_id`` for
    RLS. We decode state first, push the org into the request context,
    THEN open a session — same pattern as ``core.embed.submissions``.
    """
    if error:
        # User clicked Deny on Google's consent screen.
        return _integrations_redirect(
            status="google_calendar_denied", reason=error
        )
    if not code or not state:
        return _integrations_redirect(
            status="google_calendar_error", reason="missing_params"
        )

    # Verify state (cheap, no I/O) BEFORE touching the DB. Lets us
    # bail out on forged / expired callbacks without opening a session.
    from src.app.core.integrations.google_calendar import oauth as _oauth

    try:
        payload = _oauth.verify_state(state)
    except HTTPException:
        return _integrations_redirect(
            status="google_calendar_error", reason="invalid_state"
        )

    try:
        org_id = uuid.UUID(payload["org_id"])
        user_id = int(payload["user_id"])
    except (KeyError, ValueError, TypeError):
        return _integrations_redirect(
            status="google_calendar_error", reason="malformed_state"
        )

    ctx_token = set_context(
        RequestContext(org_id=org_id, user_id=None)
    )
    try:
        async with async_session() as session:
            try:
                await _service.complete_connection(
                    session, code=code, state=state
                )
            except HTTPException as exc:
                logger.warning(
                    "google_calendar.callback rejected status=%d detail=%s",
                    exc.status_code,
                    exc.detail,
                )
                return _integrations_redirect(
                    status="google_calendar_error",
                    reason="token_exchange_failed",
                )
            except Exception as exc:
                logger.exception(
                    "google_calendar.callback unexpected_failure org=%s user=%d",
                    org_id,
                    user_id,
                )
                return _integrations_redirect(
                    status="google_calendar_error", reason=type(exc).__name__
                )
    finally:
        reset_context(ctx_token)
    return _integrations_redirect(status="google_calendar_connected")


# --- disconnect --------------------------------------------------------


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Revoke the refresh token upstream + delete the row. Idempotent
    — returns 204 whether or not a row existed."""
    org_id = _resolve_org_id(user)
    await _service.disconnect(db, org_id=org_id, user_id=int(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- status ------------------------------------------------------------


@router.get("/status")
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Read shape for the integrations card. Frontend polls this every
    5s while the OAuth popup is open + once on mount otherwise."""
    org_id = _resolve_org_id(user)
    status_data = await _service.get_status(
        db, org_id=org_id, user_id=int(user.id)
    )
    return {
        "connected": status_data.connected,
        "google_email": status_data.google_email,
        "last_error": status_data.last_error,
        "last_synced_at": (
            status_data.last_synced_at.isoformat()
            if status_data.last_synced_at
            else None
        ),
        "scopes_granted": status_data.scopes_granted,
        "access_token_expires_at": (
            status_data.access_token_expires_at.isoformat()
            if status_data.access_token_expires_at
            else None
        ),
    }


# --- helpers -----------------------------------------------------------


def _integrations_redirect(
    *, status: str, reason: str | None = None
) -> RedirectResponse:
    """Bounce back to the Integrations page with ``?status=…`` (and an
    optional ``&reason=…``). URL-encodes both so a reason carrying
    spaces / unicode lands cleanly in the address bar."""
    params: dict[str, str] = {"status": status}
    if reason:
        params["reason"] = reason
    return RedirectResponse(
        url=f"{FRONTEND_URL}{_INTEGRATIONS_RETURN_PATH}?{urlencode(params)}",
        status_code=302,
    )


__all__ = ["router"]
