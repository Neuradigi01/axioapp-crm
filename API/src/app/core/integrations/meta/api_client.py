"""Thin Meta Graph API client used by `subscriptions.py`.

Wraps `https://graph.facebook.com/v19.0/...` calls. Differs from the
Google client in two important ways:

  - **No refresh path.** Meta doesn't issue refresh tokens; expiry is
    permanent until the user re-OAuths. `_get_access_token` just
    returns the decrypted user token verbatim.

  - **401 means "re-OAuth required".** When Meta returns 401 with an
    `OAuthException` (sub-code 463/467 typically), the user token has
    expired or the user revoked our app on Facebook. The client flips
    the integration row to `expired` + raises `MetaTokenExpiredError`
    so the caller can surface a "reconnect" CTA in the Settings UI.

The client is short-lived — instantiate per-request, make a call or
two, discard.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import META_GRAPH_API_VERSION
from src.app.core.integrations.crypto import decrypt
from src.app.core.integrations.models import (
    Integration,
    IntegrationStatus,
)

_API_BASE = "https://graph.facebook.com"
_HTTP_TIMEOUT = 15.0


class MetaTokenExpiredError(Exception):
    """Raised when Meta rejects our token. Signals that the integration
    row has been flipped to `expired` and the Owner needs to re-OAuth.
    Caller maps this to a 401 with a reconnect-CTA error body."""


class MetaGraphClient:
    """Stateful per-request client. Holds the `Integration` row + a
    DB session for the rare write that happens when a 401 marks the
    integration `expired`. `http_client` is injectable for tests."""

    def __init__(
        self,
        *,
        integration: Integration,
        session: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if integration.status != IntegrationStatus.connected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Meta integration is {integration.status.value} — reconnect required."),
            )
        self._integration = integration
        self._session = session
        self._http = http_client

    # --- public surface -------------------------------------------------

    async def get(
        self,
        path: str,
        *,
        params: dict | None = None,
        access_token: str | None = None,
    ) -> dict:
        """GET a Graph path. `access_token` defaults to the
        integration's user token; pass a Page token explicitly when
        acting on a specific Page (subscribe / unsubscribe / list
        leadgen_forms)."""
        return await self._request("GET", path, params=params, access_token=access_token)

    async def post(
        self,
        path: str,
        *,
        params: dict | None = None,
        access_token: str | None = None,
    ) -> dict:
        """POST to a Graph path. Meta's POST endpoints take params as
        querystring or form body interchangeably; we use querystring
        for parity with their docs."""
        return await self._request("POST", path, params=params, access_token=access_token)

    async def delete(
        self,
        path: str,
        *,
        params: dict | None = None,
        access_token: str | None = None,
    ) -> dict:
        return await self._request("DELETE", path, params=params, access_token=access_token)

    # --- internals ------------------------------------------------------

    def _user_token(self) -> str:
        """Decrypt the integration's user token. Always present when
        `status == connected` (guarded in __init__)."""
        if self._integration.access_token_enc is None:
            raise RuntimeError(
                f"integration {self._integration.id} has no access "
                f"token — caller bypassed the connected-status guard."
            )
        return decrypt(self._integration.access_token_enc)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None,
        access_token: str | None,
    ) -> dict:
        url = f"{_API_BASE}/{META_GRAPH_API_VERSION}/{path.lstrip('/')}"
        token = access_token or self._user_token()
        merged_params = dict(params or {})
        merged_params["access_token"] = token
        try:
            response = await self._http_call(method, url, merged_params)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Meta Graph API unreachable: {exc}",
            ) from exc

        if response.status_code == 401:
            await self._mark_expired(reason=f"401 from {method} {path}")
            raise MetaTokenExpiredError("Meta rejected the token — reconnect required.")
        if response.status_code >= 400:
            detail = _safe_json(response) or {"raw": response.text[:300]}
            # Meta returns errors with an `error` object. If it carries
            # an OAuthException sub-code we treat as expired too — Meta
            # sometimes returns 400 for revoked tokens, not 401.
            if _is_oauth_exception(detail):
                await self._mark_expired(reason=str(detail)[:200])
                raise MetaTokenExpiredError("Meta token rejected (OAuthException) — reconnect.")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(f"Meta Graph API error (status={response.status_code}): {detail}"),
            )
        body = _safe_json(response)
        return body if body is not None else {}

    async def _http_call(self, method: str, url: str, params: dict) -> httpx.Response:
        if self._http is not None:
            return await self._http.request(method, url, params=params)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            return await client.request(method, url, params=params)

    async def _mark_expired(self, *, reason: str) -> None:
        """Flip the integration row to `expired` so the Settings UI
        can surface a reconnect CTA. Commits on its own — the caller
        is about to raise."""
        self._integration.status = IntegrationStatus.expired
        self._integration.last_error = reason[:500]
        await self._session.commit()


def _safe_json(response: httpx.Response) -> dict | None:
    try:
        return response.json()
    except ValueError:
        return None


def _is_oauth_exception(detail: dict) -> bool:
    """Return True only when the Meta error indicates the ACCESS TOKEN
    itself is dead (expired, revoked, invalidated) — never for missing
    permissions, invalid params, or rate limits, all of which Meta also
    labels ``OAuthException``.

    Token-death codes:
      * 190 — access token expired / invalid / revoked (any subcode)
      * 102 — session key invalid (legacy token type)

    We deliberately do NOT match every ``type=OAuthException`` — code
    200 in particular means "permission not granted for this action",
    which is a scope problem, not a token problem. Marking the token
    ``expired`` and telling the user to reconnect would not help; they
    need to grant the missing scope in the Meta app dashboard first.
    """
    err = detail.get("error") if isinstance(detail, dict) else None
    if not isinstance(err, dict):
        return False
    code = err.get("code")
    return code in (190, 102)


__all__ = ["MetaGraphClient", "MetaTokenExpiredError"]
