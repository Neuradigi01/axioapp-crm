"""Gmail push-notification primitives (Pub/Sub).

Gmail's push model is: we register a Pub/Sub topic via `users.watch`;
Gmail publishes a message to that topic every time the user's
mailbox changes; Google Cloud Pub/Sub then POSTs an OIDC-signed
notification to our webhook (`/api/v1/email/gmail/push`). The
webhook verifies the OIDC JWT, looks up the account by emailAddress,
and enqueues an incremental sync.

Pub/Sub is OPTIONAL. When `GOOGLE_GMAIL_PUBSUB_TOPIC` is empty:

  - `watch_if_configured(...)` is a no-op (the connect flow proceeds
    without a push subscription).
  - The webhook endpoint returns 503 — there's nothing to ping it
    against.

In that fallback mode, Step 4's 60-second poll daemon does the
work. Push just adds <60s latency for orgs that have configured
GCP Pub/Sub properly. Documented in
`tasks/app-updates/email/manual-google-gmail-setup.md` (to be
authored alongside the OAuth verification kick-off).
"""
from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    GOOGLE_GMAIL_PUBSUB_SA_EMAIL,
    GOOGLE_GMAIL_PUBSUB_TOPIC,
)
from src.app.core.email.gmail.client import GmailClient, GmailHTTPError
from src.app.core.email.models import EmailAccount


logger = logging.getLogger(__name__)


_GOOGLE_OIDC_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
# Process-local cache of Google's JWKS. Refreshed lazily on signature
# mismatch — Google rotates roughly daily; pinning forever would
# eventually 401 every push.
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


def pubsub_topic_configured() -> bool:
    """True when the deployment has a Pub/Sub topic configured —
    callers branch on this to decide whether to call `users.watch`
    on connect."""
    return bool(GOOGLE_GMAIL_PUBSUB_TOPIC)


async def watch_if_configured(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GmailClient] = None,
) -> Optional[str]:
    """Register a Pub/Sub push subscription if a topic is configured.
    Returns the initial historyId from `users.watch`, which the
    caller should persist as `account.sync_cursor` so the first
    incremental sync has a starting point. Returns `None` if no
    topic is configured (push disabled in this deployment).

    Best-effort: a failure to register the watch is logged and the
    connect flow proceeds — the fallback 60-second poll still keeps
    the mailbox in sync.
    """
    if not pubsub_topic_configured():
        return None
    gc = client or GmailClient(account=account, session=session)
    try:
        body = await gc.watch(topic_name=GOOGLE_GMAIL_PUBSUB_TOPIC)
    except GmailHTTPError as exc:
        logger.warning(
            "users.watch failed for account=%s status=%s body=%s — "
            "falling back to poll-only sync",
            account.id,
            exc.status_code,
            exc.body,
        )
        return None
    return str(body.get("historyId") or "")


async def stop_watch_quiet(
    account: EmailAccount,
    session: AsyncSession,
    *,
    client: Optional[GmailClient] = None,
) -> None:
    """Tear down the Pub/Sub subscription. Idempotent: Gmail returns
    204 even for a mailbox that isn't being watched, and any error
    is logged but never raised — disconnect must always succeed
    locally even if the Gmail call fails (the tokens get nulled
    regardless)."""
    if not pubsub_topic_configured():
        return
    gc = client or GmailClient(account=account, session=session)
    try:
        await gc.stop_watch()
    except (GmailHTTPError, HTTPException) as exc:
        logger.warning(
            "users.stop failed for account=%s err=%s (ignored)",
            account.id,
            exc,
        )


# --- Push webhook validation -------------------------------------------


async def find_account_by_email(
    session: AsyncSession, email_address: str
) -> Optional[EmailAccount]:
    """Resolve an inbound push notification's `emailAddress` payload
    to an `email_accounts` row. RLS would normally hide cross-tenant
    rows, but the push handler has no tenant context yet — it LEARNS
    the tenant from this lookup. The handler then `set_context(...)`s
    the row's `org_id` before kicking off any sync work.

    Uses a raw SQL query that bypasses the ORM tenant filter for the
    same reason `core.integrations.service.get_by_webhook_secret`
    does: the email_address index is unique enough at lookup time
    (no two orgs in this deploy share a connected mailbox) and the
    push payload's OIDC signature is the auth root.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT id, org_id, user_id, provider, external_account_id,
               email_address, display_name, access_token_enc,
               refresh_token_enc, token_expires_at, scopes_granted,
               sync_cursor, sync_state, last_sync_at, last_sync_error,
               daily_sent_count, daily_sent_reset_at, connected_at,
               disconnected_at, disconnected_by
        FROM tbl_email_accounts
        WHERE provider = 'gmail'
          AND lower(email_address) = lower(:email)
          AND sync_state != 'disconnected'
        ORDER BY connected_at DESC
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"email": email_address})
    ).mappings().first()
    if row is None:
        return None
    # Instantiate the ORM model from the raw row so callers can
    # treat it like any other EmailAccount.
    from src.app.core.email.models import (
        EmailAccountProvider,
        EmailAccountSyncState,
    )

    return EmailAccount(
        id=row["id"],
        org_id=row["org_id"],
        user_id=row["user_id"],
        provider=EmailAccountProvider(row["provider"]),
        external_account_id=row["external_account_id"],
        email_address=row["email_address"],
        display_name=row["display_name"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes_granted=row["scopes_granted"] or [],
        sync_cursor=row["sync_cursor"],
        sync_state=EmailAccountSyncState(row["sync_state"]),
        last_sync_at=row["last_sync_at"],
        last_sync_error=row["last_sync_error"],
        daily_sent_count=row["daily_sent_count"],
        daily_sent_reset_at=row["daily_sent_reset_at"],
        connected_at=row["connected_at"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
    )


def decode_pubsub_message(envelope: dict) -> dict:
    """Pub/Sub push envelope → the Gmail notification payload.

    Pub/Sub wraps every push as:
      {
        "message": {
          "data": "<base64 of Gmail's JSON>",
          "messageId": "...",
          "publishTime": "..."
        },
        "subscription": "projects/.../subscriptions/..."
      }

    Gmail's inner JSON is `{"emailAddress": "...", "historyId": 12345}`.
    Returns a normalised dict; raises HTTPException(400) on a malformed
    envelope.
    """
    if not isinstance(envelope, dict) or "message" not in envelope:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Push envelope missing 'message'.",
        )
    inner = envelope["message"] or {}
    raw_data = inner.get("data") or ""
    if not raw_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Push 'message.data' is empty.",
        )
    try:
        decoded = base64.urlsafe_b64decode(raw_data + "===")
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Push 'message.data' is not base64/JSON: {exc}",
        ) from exc
    if "emailAddress" not in payload or "historyId" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Push payload missing emailAddress/historyId.",
        )
    return {
        "email_address": str(payload["emailAddress"]),
        "history_id": str(payload["historyId"]),
        "message_id": str(inner.get("messageId") or ""),
        "publish_time": str(inner.get("publishTime") or ""),
    }


async def verify_oidc_jwt(
    *,
    authorization_header: str,
    expected_audience: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Validate the OIDC token Pub/Sub sends in the `Authorization:
    Bearer …` header. Returns the decoded JWT claims on success.

    Checks:
      1. Header parses as `Bearer <token>`.
      2. Signature verifies against Google's current JWKS.
      3. `iss` is one of Google's accepted issuers.
      4. `aud` equals the configured webhook URL (Pub/Sub uses the
         subscription's pushConfig.oidcToken.audience field).
      5. `exp` is in the future.
      6. `email` matches the configured Pub/Sub SA address (when set).

    Raises HTTPException(401) on any failure with a generic message
    (don't leak signature internals to attackers).
    """
    if not authorization_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Push authorization header missing or malformed.",
        )
    token = authorization_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Push authorization header empty.",
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Push token header not parseable.",
        )
    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Push token missing 'kid'.",
        )

    jwks = await _get_jwks(http_client=http_client, force_refresh=False)
    key = _find_key(jwks, kid)
    if key is None:
        # Cache miss may mean a rotation we haven't picked up yet.
        jwks = await _get_jwks(http_client=http_client, force_refresh=True)
        key = _find_key(jwks, kid)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Push token signed by unknown key.",
        )

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[unverified_header.get("alg", "RS256")],
            audience=expected_audience,
            issuer=list(_GOOGLE_ISSUERS),
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Push token rejected: {exc}",
        )

    if GOOGLE_GMAIL_PUBSUB_SA_EMAIL:
        if claims.get("email") != GOOGLE_GMAIL_PUBSUB_SA_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Push token signer mismatch.",
            )
    return claims


async def _get_jwks(
    *, http_client: Optional[httpx.AsyncClient], force_refresh: bool
) -> dict:
    """Cached fetch of Google's JWKS. Refreshes on TTL expiry or on
    a `force_refresh=True` call (signature mismatch fallback)."""
    now = time.time()
    if (
        not force_refresh
        and _jwks_cache["keys"] is not None
        and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]
    if http_client is not None:
        response = await http_client.get(_GOOGLE_OIDC_CERTS_URL)
    else:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_GOOGLE_OIDC_CERTS_URL)
    response.raise_for_status()
    keys = response.json()
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


def _find_key(jwks: dict, kid: str) -> Optional[dict]:
    for k in (jwks.get("keys") or []):
        if k.get("kid") == kid:
            return k
    return None


def _clear_jwks_cache_for_tests() -> None:
    _jwks_cache["keys"] = None
    _jwks_cache["fetched_at"] = 0.0


__all__ = [
    "decode_pubsub_message",
    "find_account_by_email",
    "pubsub_topic_configured",
    "stop_watch_quiet",
    "verify_oidc_jwt",
    "watch_if_configured",
]
