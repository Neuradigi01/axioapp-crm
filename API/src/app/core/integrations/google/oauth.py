"""Google Ads OAuth 2.0 flow — authorize redirect + callback handler.

Two entry points:

  - `start_authorize(org_id, actor_id) -> str` builds the consent URL
    the browser will be redirected to. The `state` parameter carries
    a stdlib-HMAC-signed JSON blob with `{org_id, actor_id, nonce, exp}`
    so the callback can verify (a) it's our state, (b) it hasn't been
    tampered with, (c) it hasn't expired (10-minute TTL).
  - `handle_callback(code, state) -> Integration` is the destination
    for Google's `/callback` redirect. Verifies state, exchanges the
    authorization code for tokens via Google's token endpoint, fetches
    the user's email for `account_label`, then calls
    `service.upsert(...)` to encrypt + store the credentials.

State signing uses stdlib `hmac.HMAC(sha256)` with
`INTEGRATIONS_ENCRYPTION_KEY` as the secret. We don't carry tokens or
PII in the state — just identifiers — so an attacker who somehow
recovers the secret learns nothing useful from intercepted state values.

OAuth scope set:
  - `https://www.googleapis.com/auth/adwords` — Google Ads API access
  - `https://www.googleapis.com/auth/userinfo.email` — populate account_label
  - `openid` — standard OIDC

`access_type=offline` + `prompt=consent` together force Google to
return a refresh token on every grant (without `prompt=consent`,
Google only returns refresh tokens on the FIRST grant for a given
(client_id, user) pair — disastrous when the Owner reconnects).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_URI,
    INTEGRATIONS_ENCRYPTION_KEY,
)
from src.app.core.integrations.models import Integration
from src.app.core.integrations.schemas import IntegrationUpsert
from src.app.core.integrations.service import upsert


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Scopes for v1: enough to call listAccessibleCustomers + search the
# extension feed items (lead forms) on each customer + fetch the user's
# email for the integration row's account_label.
_SCOPES = [
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

_STATE_TTL_SECONDS = 600          # 10 minutes — Google flows complete in seconds
_TOKEN_HTTP_TIMEOUT = 10.0


def _state_secret() -> bytes:
    """HMAC secret for state signing. The Fernet key already lives in
    the env; reusing it here means one secret to rotate, not two."""
    if not INTEGRATIONS_ENCRYPTION_KEY:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY not configured — required for "
            "OAuth state signing. See .env.example."
        )
    return INTEGRATIONS_ENCRYPTION_KEY.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign_state(payload: dict) -> str:
    """Encode `{payload}` as `<b64-json>.<b64-hmac>`. Tamper-evident."""
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(
        _state_secret(), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_b64url_encode(sig)}"


def _verify_state(state: str) -> dict:
    """Decode + verify HMAC + check expiry. Raises HTTPException(400)
    on any failure. Returns the original payload dict on success."""
    if not state or state.count(".") != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        )
    body, sig = state.split(".", 1)
    expected = hmac.new(
        _state_secret(), body.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        provided = _b64url_decode(sig)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        )
    if not hmac.compare_digest(provided, expected):
        # `compare_digest` is timing-safe — important for HMAC.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state signature mismatch.",
        )
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed OAuth state.",
        )
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state has expired — try connecting again.",
        )
    return payload


# --- Public API ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoogleTokens:
    """Decoded response from Google's token endpoint. Only the fields
    we actually persist or use."""

    access_token: str
    refresh_token: Optional[str]
    expires_at: int  # unix seconds


def start_authorize(
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
) -> str:
    """Build the URL the browser should be redirected to for the
    Google OAuth consent screen.

    `nonce` is included in the state so two simultaneous connect
    attempts (e.g. user opens two tabs) can't collide. `exp` enforces
    the 10-minute TTL.
    """
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google OAuth client is not configured. Set "
                "GOOGLE_OAUTH_CLIENT_ID in .env — see "
                "tasks/ad-integrations/manual-google-oauth-setup.md."
            ),
        )
    state_payload = {
        "org_id": str(org_id),
        "actor_id": str(actor_id) if actor_id else None,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",
        # `prompt=consent` FORCES a fresh refresh token on every grant.
        # Without it, Google only returns one on the FIRST grant per
        # (client, user) — meaning a disconnect+reconnect leaves the
        # row with no refresh token, breaking long-lived sessions.
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _sign_state(state_payload),
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> GoogleTokens:
    """POST the authorization code to Google's token endpoint. Returns
    the decoded `GoogleTokens`. Raises HTTPException(502) if Google's
    response isn't a success or doesn't include the expected fields.

    `http_client` is injectable for tests (the production path opens
    a per-call client so we don't share state across requests)."""
    data = {
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = await _post_token(data, http_client)
    body = _parse_token_response(response)
    return GoogleTokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=int(time.time()) + int(body.get("expires_in", 3600)),
    )


async def fetch_userinfo_email(
    access_token: str,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """Best-effort: fetch the Google account's email for the
    integration row's `account_label`. Returns None on any failure —
    the connect doesn't fail just because the human-friendly label
    couldn't be fetched."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if http_client is not None:
            response = await http_client.get(
                _USERINFO_URL, headers=headers
            )
        else:
            async with httpx.AsyncClient(
                timeout=_TOKEN_HTTP_TIMEOUT
            ) as client:
                response = await client.get(_USERINFO_URL, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json().get("email")
    except ValueError:
        return None


async def handle_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Integration:
    """End-to-end callback handler:

      1. Verify the state (signature + freshness) → extract `org_id`.
      2. Exchange the auth code for tokens.
      3. Fetch the user's email (best effort) for the `account_label`.
      4. Upsert the integration row (Step 1's service encrypts tokens).

    Returns the persisted `Integration`. Raises HTTPException on any
    auth/exchange failure; the router converts to a redirect with an
    error param so the Settings page can show a friendly message."""
    payload = _verify_state(state)
    org_id = uuid.UUID(payload["org_id"])
    actor_id = (
        uuid.UUID(payload["actor_id"])
        if payload.get("actor_id")
        else None
    )

    tokens = await exchange_code_for_tokens(code, http_client=http_client)
    email = await fetch_userinfo_email(
        tokens.access_token, http_client=http_client
    )

    integration = await upsert(
        session,
        org_id=org_id,
        actor_id=actor_id,
        payload=IntegrationUpsert(
            provider="google_ads",
            account_id=None,  # Set by sync_forms later — Google has no single "account id" at the user level
            account_label=email,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_expires_at=_unix_to_aware(tokens.expires_at),
            scopes=_SCOPES,
        ),
    )
    return integration


# --- Helpers --------------------------------------------------------------


async def _post_token(
    data: dict, http_client: Optional[httpx.AsyncClient]
) -> httpx.Response:
    try:
        if http_client is not None:
            return await http_client.post(_TOKEN_URL, data=data)
        async with httpx.AsyncClient(
            timeout=_TOKEN_HTTP_TIMEOUT
        ) as client:
            return await client.post(_TOKEN_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token endpoint unreachable: {exc}",
        ) from exc


def _parse_token_response(response: httpx.Response) -> dict:
    """Decode + validate Google's token-endpoint response. Google
    returns 4xx on bad code / expired code / wrong client_secret;
    surface those clearly so the Owner can fix their config."""
    if response.status_code != 200:
        detail_body = _safe_json(response) or {"raw": response.text[:200]}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Google rejected the OAuth exchange "
                f"(status={response.status_code}): {detail_body}"
            ),
        )
    body = _safe_json(response)
    if not body or "access_token" not in body:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token response missing access_token.",
        )
    return body


def _safe_json(response: httpx.Response) -> Optional[dict]:
    try:
        return response.json()
    except ValueError:
        return None


def _unix_to_aware(ts: int):
    """Unix seconds → tz-aware UTC datetime. Standalone so it's
    testable without the rest of the module being imported."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc)


def verify_state(state: str) -> dict:
    """Public alias for `_verify_state` — exposed so the router can
    decode + verify the state ahead of opening a DB session (the
    callback has no JWT, so tenant context must be pushed *before* a
    session is created for RLS to attach `app.org_id`)."""
    return _verify_state(state)


__all__ = [
    "GoogleTokens",
    "exchange_code_for_tokens",
    "fetch_userinfo_email",
    "handle_callback",
    "start_authorize",
    "verify_state",
]
