"""Microsoft Graph provider-specific routes.

  GET   /api/v1/email/microsoft/authorize           → SPA fetches consent URL
  GET   /api/v1/email/microsoft/callback?code=&state=  → Graph's redirect target
  POST  /api/v1/email/microsoft/webhook                → Graph change notifications
  GET   /api/v1/email/microsoft/webhook?validationToken=…  → Graph subscription validation

`/authorize` is gated by `email.accounts.manage`. `/callback` is hit
by Microsoft's browser and uses the HMAC-signed state as its trust
root. `/webhook` (POST) is gated by the per-subscription `clientState`
HMAC. `/webhook` (GET with `validationToken`) is the one-shot
handshake fired when we register a subscription — it echoes the
token back as plain text without any signature check (Graph requires
this; the only thing it proves is that we own the URL).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.responses import PlainTextResponse, RedirectResponse

from config import FRONTEND_URL
from src.app.core.auth.dependencies import require_permissions
from src.app.core.email import service as email_service
from src.app.core.email import sync_daemon as email_sync_daemon
from src.app.core.email.microsoft import oauth as ms_oauth
from src.app.core.email.microsoft import webhook as ms_webhook
from src.app.core.email.models import EmailAccountSyncState
from src.app.core.email.oauth import (
    OAuthStateError,
    issue_state,
    verify_state,
)
from src.app.core.email.schemas import EmailAccountUpsert
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/microsoft", tags=["Email — Microsoft"])


_SETTINGS_RETURN_PATH = "/user/settings/email-accounts"


# --- 1. Authorize URL --------------------------------------------------


@router.get("/authorize")
async def authorize_endpoint(
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> dict:
    """Return the Microsoft consent URL as JSON for the SPA to
    navigate to. Signed state carries `(user_id, org_id, provider)`
    so the eventual callback can re-establish org context."""
    state = issue_state(
        user_id=str(user.legacy_uuid),
        org_id=str(user.org_id),
        provider="microsoft",
    )
    url = ms_oauth.MicrosoftProvider().authorize_url(
        state=state, redirect_uri=ms_oauth.graph_redirect_uri()
    )
    return {"url": url}


# --- 2. OAuth callback -------------------------------------------------


@router.get("/callback", include_in_schema=False)
async def callback_endpoint(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
) -> RedirectResponse:
    """Microsoft's redirect target after consent. Verifies state,
    swaps `code` for tokens, fetches `/me`, upserts the account
    row, optionally subscribes to change notifications, and bounces
    back to `/user/settings/email-accounts?status=microsoft_connected`.
    """
    if error:
        return _settings_redirect(
            status="microsoft_denied",
            reason=error_description or error,
        )
    if not code or not state:
        return _settings_redirect(status="microsoft_error", reason="missing_params")

    try:
        payload = verify_state(state)
        if payload.provider != "microsoft":
            return _settings_redirect(status="microsoft_error", reason="provider_mismatch")
        org_id = uuid.UUID(payload.org_id)
        user_id = uuid.UUID(payload.user_id)
    except (OAuthStateError, ValueError) as exc:
        logger.warning("Microsoft callback state invalid: %s", exc)
        return _settings_redirect(status="microsoft_error", reason="invalid_state")

    ctx_token = set_context(RequestContext(org_id=org_id, user_id=user_id))
    try:
        async with async_session() as session:
            try:
                tokens = await ms_oauth.MicrosoftProvider().exchange_code(
                    code=code,
                    redirect_uri=ms_oauth.graph_redirect_uri(),
                )
            except HTTPException as exc:
                logger.warning("Microsoft code exchange failed: %s", exc.detail)
                return _settings_redirect(
                    status="microsoft_error",
                    reason="exchange_failed",
                )

            me = await ms_oauth.fetch_userinfo(tokens.access_token)
            email_address = me.get("mail") or me.get("userPrincipalName")
            external_id = me.get("id") or email_address
            display_name = me.get("displayName")
            if not email_address or not external_id:
                return _settings_redirect(
                    status="microsoft_error",
                    reason="no_email_from_microsoft",
                )

            from datetime import datetime, timedelta

            expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in_seconds or 3600)
            account = await email_service.upsert(
                session,
                org_id=org_id,
                user_id=user_id,
                payload=EmailAccountUpsert(
                    provider="microsoft",
                    external_account_id=str(external_id),
                    email_address=email_address,
                    display_name=display_name,
                    access_token=tokens.access_token,
                    refresh_token=tokens.refresh_token,
                    token_expires_at=expires_at,
                    scopes_granted=tokens.scopes_granted or ms_oauth.MICROSOFT_SCOPES,
                ),
                actor_id=user_id,
            )

            # Best-effort: register Graph change-notification
            # subscription if webhook URL is configured. We store the
            # subscription id in `sync_cursor` (same column reused
            # across providers; see webhook.py docstring for the v1
            # constraint).
            sub = await ms_webhook.subscribe_if_configured(account, session)
            if sub and sub.get("id"):
                account.sync_cursor = str(sub["id"])
                account.sync_state = EmailAccountSyncState.backfilling
                await session.commit()
                await session.refresh(account)

            # Step 4 — kick off the initial 30-day backfill.
            account_id_for_enqueue = account.id
    finally:
        reset_context(ctx_token)

    email_sync_daemon.enqueue_backfill(account_id_for_enqueue)
    return _settings_redirect(status="microsoft_connected")


# --- 3. Webhook (validation + notifications) ---------------------------


@router.get("/webhook", include_in_schema=False)
async def webhook_validation_endpoint(
    validationToken: str = Query(default=""),
) -> PlainTextResponse:
    """Graph's subscription-validation handshake. Fired ONCE when
    we create a subscription; we have ~10 seconds to echo the token
    back as plain text. No signature check — the only thing this
    proves is that we own the URL. Without this, the
    `subscriptions.create` call we made fails."""
    if not ms_webhook.webhook_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Graph webhook is not configured.",
        )
    if not validationToken:
        return PlainTextResponse("", status_code=400)
    return PlainTextResponse(validationToken, status_code=200)


@router.post("/webhook", include_in_schema=False)
async def webhook_notification_endpoint(
    envelope: dict = Body(default={}),
) -> Response:
    """Inbound notification batch from Graph. Each item carries
    `clientState` (must match our HMAC), `subscriptionId`, and
    `resourceData` describing the changed message. We resolve the
    account, set org context, and log — Step 4 will enqueue a
    Celery sync task per affected account."""
    if not ms_webhook.webhook_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Graph webhook is not configured.",
        )

    items = ms_webhook.decode_notification(envelope)
    if not items:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Dedupe by subscription id — one tick of sync per account is
    # enough even if Graph batched several events for the same one.
    seen_subscriptions: set[str] = set()
    async with async_session() as session:
        for notif in items:
            sub_id = str(notif.get("subscriptionId") or "")
            if not sub_id or sub_id in seen_subscriptions:
                continue
            seen_subscriptions.add(sub_id)

            account = await ms_webhook.find_account_by_subscription_id(session, sub_id)
            if account is None:
                # Subscription belongs to a disconnected or unknown
                # account. ACK so Graph stops retrying.
                continue

            expected = ms_webhook.client_state_for(account.id)
            try:
                ms_webhook.assert_client_state(notif, expected=expected)
            except HTTPException:
                # Per-event signature mismatch: ignore that event
                # but keep processing others. Logged for forensics.
                logger.warning(
                    "Graph clientState mismatch on subscription=%s",
                    sub_id,
                )
                continue

            logger.info(
                "Graph push: account=%s sub=%s change=%s",
                account.id,
                sub_id,
                notif.get("changeType"),
            )
            # Step 4 — enqueue incremental sync. Dedupe by
            # subscription id (above) means one enqueue per account
            # per notification batch.
            email_sync_daemon.enqueue_incremental(account.id)

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
