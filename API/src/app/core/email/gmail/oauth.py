"""Gmail OAuth provider — implements the `OAuthProvider` Protocol
from `core.email.oauth` for the `gmail` provider name.

Reuses the same Google Cloud OAuth client as the Google Ads track
(`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`) but with
a different scope set (`gmail.modify`) and a separate redirect URI
so the callback path is unambiguous.

`access_type=offline` + `prompt=consent` together force Google to
return a refresh token on every grant — without `prompt=consent`,
Google only returns a refresh token on the FIRST grant for a given
`(client_id, user)` pair, which would break disconnect-then-reconnect
flows (the second grant has no refresh token, every subsequent token
expiry then bricks the connection).
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from config import (
    GOOGLE_GMAIL_REDIRECT_URI,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
)
from src.app.core.email.oauth import TokenSet


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Restricted scope `gmail.modify` covers read + send + label + history.
# `userinfo.email` populates the row's email_address; `userinfo.profile`
# populates display_name. `openid` is standard OIDC.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

_HTTP_TIMEOUT = 10.0


class GmailProvider:
    """Google Gmail implementation of the `OAuthProvider` Protocol.

    Stateless — methods take everything they need as args; the
    instance only exists so the module-level registry has a single
    object to dispatch through.
    """

    name = "gmail"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Build the Google consent URL the browser navigates to.
        The router decides which `redirect_uri` to send (must exactly
        match a URL configured on the Google Cloud OAuth client)."""
        if not GOOGLE_OAUTH_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Google OAuth client is not configured. Set "
                    "GOOGLE_OAUTH_CLIENT_ID in .env — same client as "
                    "the Google Ads track."
                ),
            )
        params = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> TokenSet:
        """Exchange the OAuth `code` for an access + refresh token
        pair. Raises `HTTPException(502)` on transport failure or
        `HTTPException(400)` on a non-200 from Google."""
        data = {
            "code": code,
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        body = await _post_token(data, http_client)
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in_seconds=int(body.get("expires_in", 3600)),
            scopes_granted=_split_scopes(body.get("scope")),
        )

    async def refresh(
        self,
        *,
        refresh_token: str,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> TokenSet:
        """Trade a refresh token for a fresh access token. Google
        does NOT return a new refresh token on refresh — the caller
        keeps the existing one. We propagate `refresh_token=None` in
        the returned `TokenSet` so `core.email.service.refresh_if_
        expired` knows not to overwrite the stored refresh ciphertext.
        """
        data = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        body = await _post_token(data, http_client)
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),  # usually None
            expires_in_seconds=int(body.get("expires_in", 3600)),
            scopes_granted=_split_scopes(body.get("scope")),
        )


async def fetch_userinfo(
    access_token: str,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Pull the `email` + `name` from Google's userinfo endpoint —
    populates `email_address` + `display_name` on the freshly-created
    `email_accounts` row. Returns `{}` if the call fails; the connect
    flow can still proceed (we just won't have a friendly label)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if http_client is not None:
            response = await http_client.get(
                _USERINFO_URL, headers=headers
            )
        else:
            async with httpx.AsyncClient(
                timeout=_HTTP_TIMEOUT
            ) as client:
                response = await client.get(_USERINFO_URL, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException):
        return {}
    if response.status_code != 200:
        return {}
    try:
        return response.json() or {}
    except ValueError:
        return {}


# --- Helpers --------------------------------------------------------------


async def _post_token(
    data: dict, http_client: Optional[httpx.AsyncClient]
) -> dict:
    """POST `data` form-encoded to Google's token endpoint, return the
    decoded JSON body. Surface clear errors on transport + 4xx."""
    try:
        if http_client is not None:
            response = await http_client.post(_TOKEN_URL, data=data)
        else:
            async with httpx.AsyncClient(
                timeout=_HTTP_TIMEOUT
            ) as client:
                response = await client.post(_TOKEN_URL, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token endpoint unreachable: {exc}",
        ) from exc
    if response.status_code != 200:
        try:
            error = response.json()
        except ValueError:
            error = {"raw": response.text[:200]}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Google rejected the OAuth exchange "
                f"(status={response.status_code}): {error}"
            ),
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token response was not JSON.",
        ) from exc
    if "access_token" not in body:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token response missing access_token.",
        )
    return body


def _split_scopes(scope_str: Optional[str]) -> list[str]:
    """Google returns the granted scopes as a single space-separated
    string. The Protocol expects a list."""
    if not scope_str:
        return list(GMAIL_SCOPES)
    return [s for s in scope_str.split(" ") if s]


def gmail_redirect_uri() -> str:
    """The callback URI configured on the Google Cloud OAuth client.
    Centralised so the router + the OAuth flow can't drift."""
    return GOOGLE_GMAIL_REDIRECT_URI


__all__ = [
    "GMAIL_SCOPES",
    "GmailProvider",
    "fetch_userinfo",
    "gmail_redirect_uri",
]
