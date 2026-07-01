"""Per-user Google Calendar OAuth 2.0 flow.

Distinct from the per-org Google Ads OAuth in :mod:`core.integrations.google.oauth`:

  * **Per-user, not per-org.** State parameter carries
    ``{org_id, user_id, nonce, exp}``. The callback verifies the state's
    ``user_id`` matches the JWT's ``user_id`` before writing anything.
  * **Requests calendar.events scope** on top of the standard OIDC bundle
    so we can populate ``google_email`` + ``google_user_id`` on the token
    row and — later, in Step 3-4 — actually push events into the
    employee's calendar.
  * **Refresh helper** :func:`get_valid_access_token` — the ONE call site
    every sync task hits to obtain a short-lived access token. Handles
    cache, refresh, and ``invalid_grant`` (revoked-side).

State signing reuses the same ``INTEGRATIONS_ENCRYPTION_KEY`` HMAC secret
the Ads flow uses. Token ciphertext uses the shared
:mod:`core.integrations.crypto` Fernet wrapper.
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
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from config import (
    GOOGLE_CALENDAR_REDIRECT_URI,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    INTEGRATIONS_ENCRYPTION_KEY,
)


# --- Constants ---------------------------------------------------------


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

_STATE_TTL_SECONDS = 600  # 10 minutes
_TOKEN_HTTP_TIMEOUT = 10.0
# Refresh proactively when the cached access token has <60s of life
# left — avoids the race where we hand a caller a token that expires
# mid-request.
_REFRESH_MARGIN_SECONDS = 60


class GoogleCalendarNotConnected(Exception):
    """Raised by :func:`get_valid_access_token` when there's no active
    token row for the user (never connected, or connection was revoked
    upstream). Sync callers catch this and skip — the operator has to
    reconnect via the integrations card."""


class GoogleCalendarOAuthError(Exception):
    """Raised on unexpected Google-side responses (5xx, malformed JSON,
    missing required fields). Not the same as
    :class:`GoogleCalendarNotConnected` — this represents a transient
    Google-side issue the caller can retry."""


# --- State signing -----------------------------------------------------


def _state_secret() -> bytes:
    if not INTEGRATIONS_ENCRYPTION_KEY:
        raise RuntimeError(
            "INTEGRATIONS_ENCRYPTION_KEY not configured — required for "
            "OAuth state signing. Add it to secrets.enc.env via "
            "`run secrets-edit`."
        )
    return INTEGRATIONS_ENCRYPTION_KEY.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign_state(payload: dict) -> str:
    body = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    sig = hmac.new(
        _state_secret(), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_state(state: str) -> dict:
    """Decode + verify HMAC + check expiry. Raises
    :class:`HTTPException(400)` on any failure. Returns the original
    payload dict on success (``org_id``, ``user_id``, ``nonce``, ``exp``)."""
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
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state has expired — try connecting again.",
        )
    return payload


# --- Public API --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoogleTokens:
    """Decoded response from Google's token endpoint."""

    access_token: str
    refresh_token: str | None
    expires_at: int  # unix seconds
    scopes_granted: list[str]


@dataclass(frozen=True, slots=True)
class GoogleUserInfo:
    """Decoded response from userinfo — used to populate the token row's
    display fields on connect."""

    google_user_id: str  # Google's stable `sub` claim
    email: str


def start_authorize(
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> str:
    """Build the Google consent URL for a specific user. State carries
    ``(org_id, user_id, nonce, exp)`` so the callback can verify (a)
    it's our state, (b) hasn't been tampered with, (c) hasn't expired,
    (d) matches the JWT's user_id at callback time."""
    if not GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google OAuth client is not configured. Set "
                "GOOGLE_OAUTH_CLIENT_ID in config.env — see "
                "tasks/google-calendar-sync/manual-google-calendar-setup.md."
            ),
        )
    state_payload = {
        "org_id": str(org_id),
        "user_id": int(user_id),
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
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
    http_client: httpx.AsyncClient | None = None,
) -> GoogleTokens:
    """POST the auth code to Google's token endpoint. Raises
    ``HTTPException(400)`` on any Google rejection (bad code / expired /
    wrong client_secret / etc.)."""
    data = {
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    response = await _post_token(data, http_client)
    body = _parse_token_response(response)
    scopes_granted = _split_scopes(body.get("scope"))
    return GoogleTokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=int(time.time()) + int(body.get("expires_in", 3600)),
        scopes_granted=scopes_granted,
    )


async def fetch_userinfo(
    access_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> GoogleUserInfo:
    """Fetch Google's userinfo. Unlike the Ads flow (best-effort) this
    is required — we can't identify the user without ``sub``, and we
    need ``email`` for the integrations card label."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if http_client is not None:
            response = await http_client.get(_USERINFO_URL, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=_TOKEN_HTTP_TIMEOUT) as client:
                response = await client.get(_USERINFO_URL, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise GoogleCalendarOAuthError(f"userinfo request failed: {exc}") from exc

    if response.status_code != 200:
        raise GoogleCalendarOAuthError(
            f"Google userinfo returned {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise GoogleCalendarOAuthError("Google userinfo returned malformed JSON") from exc

    google_user_id = body.get("id") or body.get("sub")
    email = body.get("email")
    if not google_user_id or not email:
        raise GoogleCalendarOAuthError(
            "Google userinfo missing required fields (id/sub, email)"
        )
    return GoogleUserInfo(
        google_user_id=str(google_user_id),
        email=str(email),
    )


async def refresh_access_token(
    refresh_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[str, int]:
    """Trade the long-lived refresh token for a fresh short-lived
    access token. Returns ``(access_token, expires_at_unix)``.

    Raises :class:`GoogleCalendarNotConnected` on ``invalid_grant`` (the
    user has revoked our access at accounts.google.com — the row should
    be marked ``revoked`` by the caller and the operator must reconnect).
    Raises :class:`GoogleCalendarOAuthError` on any other Google-side
    failure (transient; caller can retry)."""
    data = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        if http_client is not None:
            response = await http_client.post(_TOKEN_URL, data=data)
        else:
            async with httpx.AsyncClient(timeout=_TOKEN_HTTP_TIMEOUT) as client:
                response = await client.post(_TOKEN_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise GoogleCalendarOAuthError(f"token refresh failed: {exc}") from exc

    if response.status_code == 400:
        body = _safe_json(response) or {}
        if body.get("error") == "invalid_grant":
            raise GoogleCalendarNotConnected(
                "refresh_token was rejected by Google (invalid_grant) — "
                "the user has revoked calendar access."
            )
    if response.status_code != 200:
        raise GoogleCalendarOAuthError(
            f"Google token refresh returned {response.status_code}: "
            f"{response.text[:200]}"
        )
    body = _safe_json(response) or {}
    access_token = body.get("access_token")
    expires_in = body.get("expires_in")
    if not access_token or not expires_in:
        raise GoogleCalendarOAuthError(
            "Google token refresh response missing access_token / expires_in"
        )
    return str(access_token), int(time.time()) + int(expires_in)


async def revoke_refresh_token(
    refresh_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> bool:
    """Best-effort revoke — tell Google to invalidate the refresh token
    so a compromise of our DB doesn't leave a live grant floating.
    Returns ``True`` on Google's 200 / 400 (400 usually means already-
    revoked — still success from our POV). ``False`` on network error
    (caller logs; DB row is still deleted regardless)."""
    try:
        if http_client is not None:
            response = await http_client.post(
                _REVOKE_URL, params={"token": refresh_token}
            )
        else:
            async with httpx.AsyncClient(timeout=_TOKEN_HTTP_TIMEOUT) as client:
                response = await client.post(
                    _REVOKE_URL, params={"token": refresh_token}
                )
    except (httpx.HTTPError, httpx.TimeoutException):
        return False
    return response.status_code in (200, 400)


# --- Refresh cache — the ONE call site every sync path uses ------------


async def get_valid_access_token(
    session,
    *,
    org_id: uuid.UUID,
    user_id: int,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Return a valid (non-expired) plaintext access token for
    ``(org_id, user_id)``. Refreshes from Google's ``/token`` endpoint
    when the cached token is missing or within
    ``_REFRESH_MARGIN_SECONDS`` of expiry.

    Never returns the refresh token — callers must not persist / log
    the returned string; it lives in memory just long enough to
    authorise the Google API request that triggered the call.

    Raises :class:`GoogleCalendarNotConnected` when the user's row is
    missing / status != 'active' / refresh_token was revoked upstream.
    """
    from src.app.core.integrations.crypto import decrypt
    from src.app.core.integrations.google_calendar import data_access as _da

    row = await _da.get_active_token_for_user(
        session, org_id=org_id, user_id=user_id
    )
    if row is None:
        raise GoogleCalendarNotConnected(
            f"No active Google Calendar connection for user {user_id}"
        )

    # Cached access token still valid → return it directly.
    now = time.time()
    if (
        row.access_token_encrypted
        and row.access_token_expires_at
        and row.access_token_expires_at.timestamp() - now
        > _REFRESH_MARGIN_SECONDS
    ):
        return decrypt(row.access_token_encrypted)

    # Refresh path.
    refresh_token = decrypt(row.refresh_token_encrypted)
    try:
        access_token, expires_at_unix = await refresh_access_token(
            refresh_token, http_client=http_client
        )
    except GoogleCalendarNotConnected:
        await _da.mark_status(
            session,
            token_id=row.id,
            status="revoked",
            error="refresh_token was rejected by Google — the user revoked calendar access.",
        )
        raise

    # Persist the new cached token.
    from src.app.core.integrations.crypto import encrypt

    await _da.update_access_token(
        session,
        token_id=row.id,
        access_token_encrypted=encrypt(access_token),
        access_token_expires_at=datetime.fromtimestamp(expires_at_unix, tz=UTC),
    )
    return access_token


# --- Helpers -----------------------------------------------------------


async def _post_token(
    data: dict, http_client: httpx.AsyncClient | None
) -> httpx.Response:
    try:
        if http_client is not None:
            return await http_client.post(_TOKEN_URL, data=data)
        async with httpx.AsyncClient(timeout=_TOKEN_HTTP_TIMEOUT) as client:
            return await client.post(_TOKEN_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token endpoint unreachable: {exc}",
        ) from exc


def _parse_token_response(response: httpx.Response) -> dict:
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


def _safe_json(response: httpx.Response) -> dict | None:
    try:
        return response.json()
    except ValueError:
        return None


def _split_scopes(scope_str: str | None) -> list[str]:
    if not scope_str:
        return []
    return [s for s in scope_str.split(" ") if s]


__all__ = [
    "GoogleCalendarNotConnected",
    "GoogleCalendarOAuthError",
    "GoogleTokens",
    "GoogleUserInfo",
    "exchange_code_for_tokens",
    "fetch_userinfo",
    "get_valid_access_token",
    "refresh_access_token",
    "revoke_refresh_token",
    "start_authorize",
    "verify_state",
]
