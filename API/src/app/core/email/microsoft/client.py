"""Microsoft Graph REST client — thin httpx wrapper over the subset
of v1.0 endpoints we call:

  - `GET  /me/messages?$filter=...`          — filtered backfill
  - `GET  /me/messages/delta`                — incremental sync
  - `GET  /me/messages/{id}/$value`          — raw MIME fetch
  - `POST /me/sendMail`                      — outbound send (raw MIME)
  - `POST /subscriptions`                    — change-notification create
  - `PATCH /subscriptions/{id}`              — renew (extend expiration)
  - `DELETE /subscriptions/{id}`             — tear down

`GraphClient(account, session)` is short-lived: instantiated per
call site, used, dropped. Each request lazily refreshes the access
token via `core.email.service.refresh_if_expired` — refresh-in-the-
client means stale-token 401s never reach the caller.

Per-request 429 backoff: Graph returns 429 with a `Retry-After`
header when the per-tenant rate limit is hit. The client honours
the header value (or a default of 30s) for up to two retries before
giving up. Beyond that the caller sees `GraphHTTPError(429)` and
the daemon (Step 4) can defer.

`http_client` is injectable for tests; production callers pass
None and get a fresh httpx client per call.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email import service as email_service
from src.app.core.email.models import EmailAccount, EmailAccountSyncState

_API_BASE = "https://graph.microsoft.com/v1.0"
_HTTP_TIMEOUT = 30.0
_DEFAULT_RETRY_AFTER = 30.0
_MAX_429_RETRIES = 2


class GraphHTTPError(RuntimeError):
    """Raised when Graph returns an unexpected non-2xx. Carries the
    upstream status code so callers can branch on 410 (delta-link
    expired → full re-backfill), 404 (resource gone), etc."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Graph API {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class GraphClient:
    """Per-call client. Mirrors Gmail's GmailClient surface but
    speaks Microsoft Graph."""

    def __init__(
        self,
        *,
        account: EmailAccount,
        session: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if account.sync_state == EmailAccountSyncState.disconnected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"email_account {account.id} is disconnected — reconnect required."),
            )
        self._account = account
        self._session = session
        self._http = http_client

    # --- Messages ------------------------------------------------------

    async def list_messages(
        self,
        *,
        filter_expr: str | None = None,
        select: str | None = None,
        top: int = 50,
        order_by: str | None = None,
    ) -> dict:
        """`GET /me/messages` with `$filter` / `$select` / `$top`.
        Used by backfill. Returns the decoded JSON `{value: [...],
        @odata.nextLink?: "..."}`. Caller follows nextLink via
        `get_absolute(...)` to walk pages."""
        params: dict[str, Any] = {"$top": top}
        if filter_expr:
            params["$filter"] = filter_expr
        if select:
            params["$select"] = select
        if order_by:
            params["$orderby"] = order_by
        return await self._get("/me/messages", params=params)

    async def list_messages_delta(
        self,
        *,
        select: str | None = None,
        top: int = 50,
    ) -> dict:
        """`GET /me/messages/delta` — initial delta call to seed the
        cursor. Subsequent incremental syncs hit the returned
        `@odata.deltaLink` URL directly via `get_absolute`."""
        params: dict[str, Any] = {"$top": top}
        if select:
            params["$select"] = select
        return await self._get("/me/messages/delta", params=params)

    async def get_absolute(self, url: str) -> dict:
        """Hit an absolute URL returned by Graph as `@odata.nextLink`
        or `@odata.deltaLink`. These URLs already carry every query
        parameter (`$skiptoken`, `$deltatoken`, etc) so we MUST NOT
        add or modify them."""
        return await self._request("GET", absolute_url=url)

    async def get_message_raw(self, message_id: str) -> bytes:
        """`GET /me/messages/{id}/$value` — returns the raw MIME
        bytes (RFC 822). Used by Step 5's adapter when persisting
        a matched message."""
        return await self._request_bytes("GET", f"/me/messages/{message_id}/$value")

    async def send_raw(self, *, raw_b64: str) -> None:
        """`POST /me/sendMail` with `Content-Type: text/plain` and
        a base64-encoded MIME body. Graph returns 202 No Content;
        no message id comes back from this surface (Step 5 uses the
        outbound MIME's `Message-ID` header to correlate replies).
        """
        await self._request(
            "POST",
            "/me/sendMail",
            raw_body=raw_b64.encode("ascii"),
            content_type="text/plain",
            expect_json=False,
        )

    # --- Subscriptions (change notifications) --------------------------

    async def create_subscription(self, *, payload: dict) -> dict:
        """`POST /subscriptions` — registers a change-notification
        subscription. `payload` includes `changeType`,
        `notificationUrl`, `resource`, `expirationDateTime`,
        `clientState`. Returns Graph's subscription object."""
        return await self._request("POST", "/subscriptions", json=payload)

    async def renew_subscription(self, subscription_id: str, *, new_expiration_iso: str) -> dict:
        """`PATCH /subscriptions/{id}` — extends `expirationDateTime`.
        Mail subscriptions max out at 3 days; renew every 2."""
        return await self._request(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            json={"expirationDateTime": new_expiration_iso},
        )

    async def delete_subscription(self, subscription_id: str) -> None:
        """`DELETE /subscriptions/{id}`. Idempotent: 404 on an
        already-deleted subscription is treated as success."""
        try:
            await self._request(
                "DELETE",
                f"/subscriptions/{subscription_id}",
                expect_json=False,
            )
        except GraphHTTPError as exc:
            if exc.status_code != 404:
                raise

    # --- Private -------------------------------------------------------

    async def _get(self, path: str, *, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def _request(
        self,
        method: str,
        path: str | None = None,
        *,
        absolute_url: str | None = None,
        params: dict | None = None,
        json: dict | None = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        expect_json: bool = True,
    ) -> dict:
        access_token = await self._access_token()
        url = absolute_url or f"{_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }
        attempt = 0
        while True:
            response = await self._http_call(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                raw_body=raw_body,
            )
            if response.status_code == 429 and attempt < _MAX_429_RETRIES:
                # Honour Retry-After when present; fall back to default.
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                await asyncio.sleep(retry_after)
                attempt += 1
                continue
            break

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {"raw": response.text[:300]}
            raise GraphHTTPError(response.status_code, body)
        if not expect_json:
            return {}
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json() or {}
        except ValueError:
            return {}

    async def _request_bytes(self, method: str, path: str) -> bytes:
        """Bytes-returning variant for `$value` raw-MIME fetches."""
        access_token = await self._access_token()
        url = f"{_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await self._http_call(method, url, headers=headers)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {"raw": response.text[:300]}
            raise GraphHTTPError(response.status_code, body)
        return response.content

    async def _http_call(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        params: dict | None = None,
        json: dict | None = None,
        raw_body: bytes | None = None,
    ) -> httpx.Response:
        try:
            if self._http is not None:
                return await self._http.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    content=raw_body,
                )
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                return await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    content=raw_body,
                )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise GraphHTTPError(0, f"transport error: {exc}") from exc

    async def _access_token(self) -> str:
        tokens = await email_service.refresh_if_expired(self._session, account=self._account)
        return tokens.access_token


def _parse_retry_after(header_value: str | None) -> float:
    """Graph sends `Retry-After` as either a number of seconds or
    an HTTP date. We only honour the seconds form (the common one);
    HTTP date falls back to default."""
    if not header_value:
        return _DEFAULT_RETRY_AFTER
    try:
        return max(0.0, float(header_value))
    except ValueError:
        return _DEFAULT_RETRY_AFTER


__all__ = ["GraphClient", "GraphHTTPError"]
