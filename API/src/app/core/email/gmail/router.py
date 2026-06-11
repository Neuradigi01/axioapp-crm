"""Gmail provider-specific routes.

  GET   /api/v1/email/gmail/authorize           → SPA fetches consent URL
  GET   /api/v1/email/gmail/callback?code=&state=  → Google's redirect target
  POST  /api/v1/email/gmail/push                → Pub/Sub push receiver

The `/authorize` endpoint is gated by `email.accounts.manage` — the
rep connecting their own mailbox. The `/callback` is hit by Google's
browser and has no JWT; the HMAC-signed `state` is its trust root.
The `/push` is hit by Google Cloud Pub/Sub and is gated by the OIDC
JWT in the `Authorization: Bearer …` header.
"""
from __future__ import annotations

import logging
import uuid
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_BASE_URL, FRONTEND_URL
from src.app.core.auth.dependencies import require_permissions
from src.app.core.email import service as email_service
from src.app.core.email.gmail import oauth as gmail_oauth
from src.app.core.email.gmail import push as gmail_push
from src.app.core.email.gmail.client import GmailClient, GmailHTTPError
from src.app.core.email.models import EmailAccountSyncState
from src.app.core.email.oauth import (
    OAuthStateError,
    issue_state,
    verify_state,
)
from src.app.core.email.schemas import EmailAccountUpsert
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session, get_db


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/gmail", tags=["Email — Gmail"])


# Where the Settings page lives. The callback redirects here with
# a `?status=...` param so the SPA can show a toast.
_SETTINGS_RETURN_PATH = "/user/settings/email-accounts"


# --- 1. Authorize URL --------------------------------------------------


@router.get("/authorize")
async def authorize_endpoint(
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> dict:
    """Return the Google OAuth consent URL as JSON. The SPA navigates
    to it via `window.location.assign(url)`. We do NOT 302 here
    because a top-level browser GET to `/api/v1/...` doesn't carry
    the Bearer header.

    The signed `state` carries the active tenant + actor so the
    eventual `/callback` (unauthenticated; Google's browser hits it)
    can re-establish org context for the upsert.
    """
    state = issue_state(
        user_id=str(user.legacy_uuid),
        org_id=str(user.org_id),
        provider="gmail",
    )
    url = gmail_oauth.GmailProvider().authorize_url(
        state=state, redirect_uri=gmail_oauth.gmail_redirect_uri()
    )
    return {"url": url}


# --- 2. OAuth callback -------------------------------------------------


@router.get("/callback", include_in_schema=False)
async def callback_endpoint(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
) -> RedirectResponse:
    """Google's redirect target after consent. Verifies state, swaps
    `code` for tokens, fetches the user's email, upserts an
    `email_accounts` row, and bounces back to the Settings page.

    The flow has NO JWT — middleware leaves `RequestContext.org_id`
    empty. We decode the state first, push the org into the request
    context, THEN open a session (RLS needs `app.org_id` set BEFORE
    the session's `after_begin` hook fires).
    """
    if error:
        return _settings_redirect(status="gmail_denied", reason=error)
    if not code or not state:
        return _settings_redirect(
            status="gmail_error", reason="missing_params"
        )

    try:
        payload = verify_state(state)
        if payload.provider != "gmail":
            return _settings_redirect(
                status="gmail_error", reason="provider_mismatch"
            )
        org_id = uuid.UUID(payload.org_id)
        user_id = uuid.UUID(payload.user_id)
    except (OAuthStateError, ValueError) as exc:
        logger.warning("Gmail callback state invalid: %s", exc)
        return _settings_redirect(
            status="gmail_error", reason="invalid_state"
        )

    ctx_token = set_context(
        RequestContext(org_id=org_id, user_id=user_id)
    )
    try:
        async with async_session() as session:
            try:
                tokens = await gmail_oauth.GmailProvider().exchange_code(
                    code=code,
                    redirect_uri=gmail_oauth.gmail_redirect_uri(),
                )
            except HTTPException as exc:
                logger.warning(
                    "Gmail code exchange failed: %s", exc.detail
                )
                return _settings_redirect(
                    status="gmail_error", reason="exchange_failed"
                )

            userinfo = await gmail_oauth.fetch_userinfo(
                tokens.access_token
            )
            email_address = userinfo.get("email")
            if not email_address:
                return _settings_redirect(
                    status="gmail_error", reason="no_email_from_google"
                )

            from datetime import datetime, timedelta, timezone

            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=tokens.expires_in_seconds or 3600)
            )
            account = await email_service.upsert(
                session,
                org_id=org_id,
                user_id=user_id,
                payload=EmailAccountUpsert(
                    provider="gmail",
                    external_account_id=email_address,
                    email_address=email_address,
                    display_name=userinfo.get("name"),
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    token_expires_at=expires_at,
                    scopes_granted=tokens.scopes_granted
                    or gmail_oauth.GMAIL_SCOPES,
                ),
                actor_id=user_id,
            )

            # Best-effort: register a Pub/Sub push subscription if
            # the topic is configured AND seed the sync_cursor from
            # the returned historyId. Failure falls back to poll.
            history_id = await gmail_push.watch_if_configured(
                account, session
            )
            if history_id:
                account.sync_cursor = history_id
                account.sync_state = EmailAccountSyncState.backfilling
                await session.commit()
                await session.refresh(account)
    finally:
        reset_context(ctx_token)

    return _settings_redirect(status="gmail_connected")


# --- 3. Pub/Sub push receiver ------------------------------------------


@router.post("/push", include_in_schema=False)
async def push_endpoint(
    request: Request,
    envelope: dict = Body(default={}),
) -> Response:
    """Inbound Pub/Sub push notification. Verifies the OIDC JWT,
    decodes the Gmail payload, resolves the connected account, sets
    org context, and triggers an incremental sync via Step 4's
    daemon (when wired). For Step 2 the trigger is best-effort
    logging only — we have the verified payload + the matched
    account; Step 4 will enqueue the Celery task.
    """
    if not gmail_push.pubsub_topic_configured():
        # Push is disabled in this deploy. Returning 503 tells Pub/Sub
        # to back off rather than retrying forever.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail Pub/Sub push is not configured.",
        )

    # The push subscription's OIDC `audience` should be set to this
    # webhook URL. We accept either the configured prod URL or the
    # local-dev fallback (router-resolved).
    expected_audience = (
        f"{API_BASE_URL.rstrip('/')}/api/v1/email/gmail/push"
    )
    await gmail_push.verify_oidc_jwt(
        authorization_header=request.headers.get("authorization", ""),
        expected_audience=expected_audience,
    )

    payload = gmail_push.decode_pubsub_message(envelope)

    # Look up the account without a tenant context (push has no JWT;
    # the lookup uses a raw SQL query, same as integration webhooks).
    async with async_session() as session:
        account = await gmail_push.find_account_by_email(
            session, payload["email_address"]
        )
        if account is None:
            # Pub/Sub is delivering a notification for an account we
            # don't recognise — either disconnected or stale. ACK with
            # 204 so Pub/Sub stops retrying. (Returning 4xx would
            # cause Pub/Sub to keep redelivering.)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        # We have the org. Step 4 will enqueue a Celery sync task
        # here; for Step 2 we just log + acknowledge.
        logger.info(
            "Gmail push: account=%s history_id=%s message_id=%s",
            account.id,
            payload["history_id"],
            payload["message_id"],
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- helpers ----------------------------------------------------------


def _settings_redirect(*, status: str, reason: str = "") -> RedirectResponse:
    qs = {"status": status}
    if reason:
        qs["reason"] = reason
    return RedirectResponse(
        url=f"{FRONTEND_URL.rstrip('/')}{_SETTINGS_RETURN_PATH}?{urlencode(qs)}",
        status_code=302,
    )
