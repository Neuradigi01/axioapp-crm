"""Microsoft Graph OAuth provider.

Implements the `OAuthProvider` Protocol from `core.email.oauth` for
the `microsoft` provider name. Reuses the same OAuth-state HMAC
signing (`oauth.issue_state` / `verify_state`) so the callback
verification chain matches Gmail's.

Notable differences from Gmail:
  - **Refresh tokens rotate.** Microsoft returns a NEW refresh token
    on every refresh; the caller persists the new one. Google
    typically returns None on refresh (callers keep the existing).
  - **No `access_type=offline` param.** Microsoft uses
    `prompt=consent` + `offline_access` scope together to issue a
    refresh token. Both must be present.
  - **Tenant path segment.** The authorize/token URL embeds a
    tenant id: `common` for multi-tenant, a GUID for single-tenant.

OAuth scopes (minimum) for the email track:
  - `Mail.ReadWrite`  — list/get/delete messages + create drafts.
  - `Mail.Send`       — send via sendMail.
  - `offline_access`  — refresh-token issuance.
  - `User.Read`       — populate email_address + display_name via
                         /me userinfo.
  - `openid email profile` — standard OIDC scopes; tolerated by
                              Graph and round-tripped harmlessly.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from config import (
    MICROSOFT_CLIENT_ID,
    MICROSOFT_CLIENT_SECRET,
    MICROSOFT_GRAPH_REDIRECT_URI,
    MICROSOFT_TENANT,
)
from src.app.core.email.oauth import TokenSet

# Microsoft consent + token endpoints. `{tenant}` is filled at call
# time so a single OAuth client can serve `common` (default) plus
# explicit-tenant overrides in tests.
_AUTHORIZE_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"

MICROSOFT_SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "offline_access",
    "User.Read",
    "openid",
    "email",
    "profile",
]

_HTTP_TIMEOUT = 10.0


class MicrosoftProvider:
    """Microsoft 365 / Outlook implementation of `OAuthProvider`."""

    name = "microsoft"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Build the Microsoft consent URL the browser navigates to."""
        if not MICROSOFT_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Microsoft OAuth client is not configured. Set "
                    "MICROSOFT_CLIENT_ID in .env — see "
                    "tasks/app-updates/email/step-3-backend-outlook-adapter.md."
                ),
            )
        params = {
            "client_id": MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(MICROSOFT_SCOPES),
            "state": state,
            # `prompt=consent` forces the consent screen even on a
            # subsequent grant — same role as Google's `prompt=consent`,
            # guarantees a refresh token comes back.
            "prompt": "consent",
        }
        url_base = _AUTHORIZE_URL_TEMPLATE.format(tenant=MICROSOFT_TENANT)
        return f"{url_base}?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> TokenSet:
        """Exchange the OAuth `code` for tokens."""
        data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(MICROSOFT_SCOPES),
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
        http_client: httpx.AsyncClient | None = None,
    ) -> TokenSet:
        """Trade a refresh token for a fresh access + (rotated)
        refresh token pair. Microsoft DOES rotate refresh tokens on
        refresh — the caller MUST persist the new one if returned.
        """
        data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(MICROSOFT_SCOPES),
        }
        body = await _post_token(data, http_client)
        return TokenSet(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in_seconds=int(body.get("expires_in", 3600)),
            scopes_granted=_split_scopes(body.get("scope")),
        )


async def fetch_userinfo(
    access_token: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict:
    """Pull `id`, `mail`/`userPrincipalName`, `displayName` from
    Graph's `/me` endpoint. Populates `external_account_id`,
    `email_address`, `display_name` on the freshly-created
    `email_accounts` row. Returns `{}` on failure — the callback
    then 302s with `reason=no_email_from_microsoft`.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if http_client is not None:
            response = await http_client.get(_USERINFO_URL, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.get(_USERINFO_URL, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException):
        return {}
    if response.status_code != 200:
        return {}
    try:
        return response.json() or {}
    except ValueError:
        return {}


def graph_redirect_uri() -> str:
    """Centralised so router + OAuth helpers can't drift."""
    return MICROSOFT_GRAPH_REDIRECT_URI


# --- Helpers --------------------------------------------------------------


async def _post_token(data: dict, http_client: httpx.AsyncClient | None) -> dict:
    """POST `data` form-encoded to Microsoft's token endpoint."""
    url = _TOKEN_URL_TEMPLATE.format(tenant=MICROSOFT_TENANT)
    try:
        if http_client is not None:
            response = await http_client.post(url, data=data)
        else:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(url, data=data)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Microsoft token endpoint unreachable: {exc}",
        ) from exc
    if response.status_code != 200:
        try:
            error = response.json()
        except ValueError:
            error = {"raw": response.text[:200]}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Microsoft rejected the OAuth exchange (status={response.status_code}): {error}"
            ),
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Microsoft token response was not JSON.",
        ) from exc
    if "access_token" not in body:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Microsoft token response missing access_token.",
        )
    return body


def _split_scopes(scope_str: str | None) -> list[str]:
    if not scope_str:
        return list(MICROSOFT_SCOPES)
    return [s for s in scope_str.split(" ") if s]


__all__ = [
    "MICROSOFT_SCOPES",
    "MicrosoftProvider",
    "fetch_userinfo",
    "graph_redirect_uri",
]
