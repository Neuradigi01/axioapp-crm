"""Meta OAuth 2.0 flow — Facebook Login + long-lived-token exchange.

Two entry points (same shape as `google/oauth.py`):

  - `start_authorize(org_id, actor_id) -> str` returns the consent URL
    on `facebook.com/v19.0/dialog/oauth`. State is HMAC-signed via the
    same Fernet key the Google flow uses, with a `provider=meta`
    discriminator in the payload so a Google state can't be replayed
    against this callback and vice versa.

  - `handle_callback(session, code, state) -> Integration` exchanges
    the auth code for a short-lived user token, immediately re-exchanges
    that for a long-lived user token (60-day TTL), fetches the user's
    `/me` profile for the integration row's `account_label`, and
    upserts via Step-1's `service.upsert`.

Meta-specific quirks vs. Google:

  - No refresh tokens. The long-lived user token expires after 60
    days; re-OAuth is required. We persist `token_expires_at` so the
    Settings UI can warn the Owner ahead of time, but there's no
    automatic refresh path.
  - Scopes are Facebook-specific: `pages_show_list +
    pages_read_engagement + pages_manage_metadata + leads_retrieval +
    business_management`. The first three let us list + subscribe to
    Pages; `leads_retrieval` is what unlocks the Lead-Ads payload
    fields on the webhook; `business_management` lets the user see
    Pages they manage through Business Manager rather than directly.
  - `leads_retrieval` requires Meta App Review for production. Test
    users on the app dashboard can grant it in dev mode without
    review — the manual-meta-oauth-setup.md checklist explains.
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
from datetime import UTC
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    INTEGRATIONS_ENCRYPTION_KEY,
    META_APP_ID,
    META_APP_SECRET,
    META_GRAPH_API_VERSION,
    META_OAUTH_REDIRECT_URI,
)
from src.app.core.integrations.models import Integration
from src.app.core.integrations.schemas import IntegrationUpsert
from src.app.core.integrations.service import upsert

_AUTHORIZE_URL = "https://www.facebook.com/{ver}/dialog/oauth"
_TOKEN_URL = "https://graph.facebook.com/{ver}/oauth/access_token"
_USERINFO_URL = "https://graph.facebook.com/{ver}/me"

# Five scopes — the spec'd v1 set. Don't add scopes opportunistically;
# every scope added widens the App Review surface area at Meta.
_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_manage_ads",
    "leads_retrieval",
    "business_management",
]

# State TTL — same 10-min window as Google. The OAuth dance never
# takes more than a few seconds; 10 min covers users with slow Wi-Fi
# or a multi-step Business Manager picker.
_STATE_TTL_SECONDS = 600
_HTTP_TIMEOUT = 10.0
# Provider discriminator inside the signed state. Prevents a stolen
# Google state from being replayed against the Meta callback handler
# (the HMAC alone would accept it; this check refuses cross-provider).
_PROVIDER_TAG = "meta"


def _state_secret() -> bytes:
    """HMAC secret for state signing. Reuses the Fernet key from
    `INTEGRATIONS_ENCRYPTION_KEY` — one secret to rotate, not two."""
    if not INTEGRATIONS_ENCRYPTION_KEY:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY not configured — required for "
            "OAuth state signing. Add it to secrets.enc.env via `run secrets-edit`."
        )
    return INTEGRATIONS_ENCRYPTION_KEY.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign_state(payload: dict) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_state_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_state(state: str) -> dict:
    """Decode + verify HMAC + check expiry + check provider tag.
    Public so the router can extract the org_id ahead of opening a DB
    session (callback has no JWT — tenant context must be pushed
    BEFORE the session opens for RLS to attach `app.org_id`)."""
    if not state or state.count(".") != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        )
    body, sig = state.split(".", 1)
    expected = hmac.new(_state_secret(), body.encode("ascii"), hashlib.sha256).digest()
    try:
        provided = _b64url_decode(sig)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        ) from None
    if not hmac.compare_digest(provided, expected):
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
        ) from None
    if payload.get("provider") != _PROVIDER_TAG:
        # Defence against a Google state being replayed here. Both
        # providers use the same secret, so HMAC alone would accept it.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is not for this provider.",
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
class MetaTokens:
    """Decoded long-lived user token. Meta does NOT return a refresh
    token; once `expires_at` passes, re-OAuth is the only recourse."""

    access_token: str
    expires_at: int  # unix seconds


def start_authorize(
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> str:
    """Build the Facebook consent URL the browser is redirected to.
    `nonce` defangs two concurrent connect attempts (e.g. user opens
    two tabs); `exp` enforces the 10-min state TTL; `provider=meta`
    prevents cross-provider state replay."""
    if not META_APP_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Meta OAuth app is not configured. Set META_APP_ID in "
                "config.env — see tasks/ad-integrations/manual-meta-oauth-setup.md."
            ),
        )
    state_payload = {
        "provider": _PROVIDER_TAG,
        "org_id": str(org_id),
        "actor_id": str(actor_id) if actor_id else None,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    params = {
        "client_id": META_APP_ID,
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(_SCOPES),  # Meta uses comma-separated, not space
        "state": _sign_state(state_payload),
    }
    return f"{_AUTHORIZE_URL.format(ver=META_GRAPH_API_VERSION)}?{urlencode(params)}"


async def exchange_code_for_short_token(
    code: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """First leg: code → short-lived (1-hour) user token. GETs the
    token endpoint with query params — Meta accepts both GET and POST
    for this; we use GET to match Meta's docs exactly."""
    params = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "code": code,
    }
    url = _TOKEN_URL.format(ver=META_GRAPH_API_VERSION)
    body = _parse_meta_response(
        await _safe_get(url, params, http_client),
        endpoint="token exchange",
    )
    token = body.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Meta token response missing access_token.",
        )
    return token


async def exchange_for_long_lived_token(
    short_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> MetaTokens:
    """Second leg: short-lived → long-lived (60-day) user token. Meta
    discards the short token after exchange. The long-lived token is
    what we persist — it survives across Page-token derivations."""
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "fb_exchange_token": short_token,
    }
    url = _TOKEN_URL.format(ver=META_GRAPH_API_VERSION)
    body = _parse_meta_response(
        await _safe_get(url, params, http_client),
        endpoint="long-lived exchange",
    )
    token = body.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Meta long-lived token response missing access_token.",
        )
    # `expires_in` for fb_exchange_token is typically ~5184000s (60d).
    # Default to 60 days if Meta omits it (their docs are vague on
    # whether omission means "never expires" for some token classes —
    # safer to give the Settings UI a defined expiry to display).
    expires_in = int(body.get("expires_in", 60 * 24 * 60 * 60))
    return MetaTokens(access_token=token, expires_at=int(time.time()) + expires_in)


async def fetch_userinfo_label(
    access_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> str | None:
    """Best-effort: fetch the FB user's display name + email for the
    `account_label`. Returns None on any failure — connect doesn't
    fail just because the label couldn't be fetched."""
    url = _USERINFO_URL.format(ver=META_GRAPH_API_VERSION)
    params = {"fields": "id,name,email", "access_token": access_token}
    try:
        response = await _safe_get(url, params, http_client)
    except HTTPException:
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    # Prefer email when granted (the `email` scope isn't in our list,
    # so this is usually None for non-business accounts). Fall back
    # to display name, then to the FB user id.
    return body.get("email") or body.get("name") or body.get("id")


async def handle_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str,
    http_client: httpx.AsyncClient | None = None,
) -> Integration:
    """End-to-end callback handler:

    1. Verify state (signature + freshness + provider).
    2. code → short token → long-lived token.
    3. Fetch user label (best effort).
    4. Upsert the integration row via Step-1's encrypted-token service.
    """
    payload = verify_state(state)
    org_id = uuid.UUID(payload["org_id"])
    actor_id = uuid.UUID(payload["actor_id"]) if payload.get("actor_id") else None

    short_token = await exchange_code_for_short_token(code, http_client=http_client)
    tokens = await exchange_for_long_lived_token(short_token, http_client=http_client)
    label = await fetch_userinfo_label(tokens.access_token, http_client=http_client)

    integration = await upsert(
        session,
        org_id=org_id,
        actor_id=actor_id,
        payload=IntegrationUpsert(
            provider="meta_ads",
            account_id=None,  # We don't have a single "account id" — pages live under the user
            account_label=label,
            access_token=tokens.access_token,
            refresh_token=None,  # Meta has no refresh tokens
            token_expires_at=_unix_to_aware(tokens.expires_at),
            scopes=_SCOPES,
        ),
    )
    return integration


# --- helpers --------------------------------------------------------------


async def _safe_get(
    url: str,
    params: dict,
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    """GET wrapper that turns network errors into HTTPException(502)
    so the router can map them to a friendly redirect."""
    try:
        if http_client is not None:
            return await http_client.get(url, params=params)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            return await client.get(url, params=params)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Meta endpoint unreachable: {exc}",
        ) from exc


def _parse_meta_response(response: httpx.Response, *, endpoint: str) -> dict:
    """Decode + validate Meta's response. 4xx → 400 with the upstream
    error body so the Owner can fix their config; 5xx → 502."""
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(f"Meta {endpoint} returned {response.status_code}: {response.text[:200]}"),
        )
    body: dict
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Meta {endpoint} returned non-JSON.",
        ) from None
    if response.status_code >= 400 or "error" in body:
        err = body.get("error") or {"raw": response.text[:200]}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Meta {endpoint} rejected: {err}",
        )
    return body


def _unix_to_aware(ts: int):
    from datetime import datetime

    return datetime.fromtimestamp(ts, tz=UTC)


__all__ = [
    "MetaTokens",
    "exchange_code_for_short_token",
    "exchange_for_long_lived_token",
    "fetch_userinfo_label",
    "handle_callback",
    "start_authorize",
    "verify_state",
]
