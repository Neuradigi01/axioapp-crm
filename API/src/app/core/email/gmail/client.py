"""Thin httpx wrapper over the subset of the Gmail REST API we call.

Endpoints covered:
  - `users.messages.list`        — discover messages for backfill.
  - `users.messages.get`         — fetch raw or metadata for one msg.
  - `users.history.list`         — incremental sync from a historyId.
  - `users.messages.send`        — outbound send.
  - `users.watch` / `users.stop` — Pub/Sub push subscription lifecycle.

`GmailClient(account, session)` is short-lived: instantiated per
call site, used, dropped. Each request lazily refreshes the access
token via `core.email.service.refresh_if_expired` — keeping refresh
inside the client (not in a separate cron) means stale-token errors
literally cannot reach the caller.

`http_client` is injectable for tests; production callers pass
`None` and get a fresh httpx client per call (cheap)."""
from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email import service as email_service
from src.app.core.email.models import EmailAccount, EmailAccountSyncState


_API_BASE = "https://gmail.googleapis.com/gmail/v1"
_HTTP_TIMEOUT = 30.0


class GmailHTTPError(RuntimeError):
    """Raised when Gmail returns an unexpected non-2xx. Carries the
    upstream status code so callers can branch on 404 (historyId
    expired → full re-backfill) without scraping the message."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Gmail API {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class GmailClient:
    """Per-call client. Pass the `EmailAccount` row + the session it
    was loaded on. Each public method (`list_messages`, `get_message`,
    `list_history`, `send_message`, `watch`, `stop_watch`) refreshes
    the access token first via `refresh_if_expired`, persisting the
    rotated ciphertext if a refresh fired."""

    def __init__(
        self,
        *,
        account: EmailAccount,
        session: AsyncSession,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if account.sync_state == EmailAccountSyncState.disconnected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"email_account {account.id} is disconnected — "
                    "reconnect required."
                ),
            )
        self._account = account
        self._session = session
        self._http = http_client

    # --- public Gmail surface ------------------------------------------

    async def list_messages(
        self,
        *,
        q: Optional[str] = None,
        page_token: Optional[str] = None,
        max_results: int = 100,
    ) -> dict:
        """`users.messages.list` — used by backfill. `q` is the Gmail
        search syntax (e.g. `newer_than:30d`). Returns the decoded
        JSON envelope `{messages: [{id, threadId}], nextPageToken}`."""
        params: dict[str, Any] = {"maxResults": max_results}
        if q:
            params["q"] = q
        if page_token:
            params["pageToken"] = page_token
        return await self._get("/users/me/messages", params=params)

    async def get_message(
        self, message_id: str, *, format: str = "metadata"
    ) -> dict:
        """`users.messages.get` — `format` is one of `minimal`,
        `metadata` (headers only), `full` (parsed payload), or `raw`
        (base64url-encoded MIME). Backfill uses `metadata` first to
        check the from/to without paying the full-bytes cost."""
        params = {"format": format}
        if format == "metadata":
            # Limit metadata response to the headers we care about;
            # cuts payload size by ~70%.
            params["metadataHeaders"] = [
                "From",
                "To",
                "Cc",
                "Bcc",
                "Subject",
                "Date",
                "Message-ID",
                "In-Reply-To",
                "References",
            ]
        return await self._get(
            f"/users/me/messages/{message_id}", params=params
        )

    async def list_history(
        self,
        *,
        start_history_id: str,
        page_token: Optional[str] = None,
        history_types: Optional[list[str]] = None,
    ) -> dict:
        """`users.history.list` — incremental sync. Each event in
        `.history` is `{messagesAdded, messagesDeleted, ...}`.
        Returns `{}` if no events since `start_history_id`."""
        params: dict[str, Any] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        if history_types:
            params["historyTypes"] = history_types
        return await self._get("/users/me/history", params=params)

    async def send_message(
        self,
        *,
        raw_b64url: str,
        thread_id: Optional[str] = None,
    ) -> dict:
        """`users.messages.send` — `raw_b64url` is the message MIME
        encoded as URL-safe base64 (no padding). Returns
        `{id, threadId, labelIds}` from Gmail."""
        body: dict[str, Any] = {"raw": raw_b64url}
        if thread_id is not None:
            body["threadId"] = thread_id
        return await self._post("/users/me/messages/send", json=body)

    async def watch(self, *, topic_name: str) -> dict:
        """`users.watch` — register a Pub/Sub push subscription.
        Returns `{historyId, expiration}`. Watches expire after 7
        days; Step 4's daemon renews every 6 days."""
        body = {
            "topicName": topic_name,
            "labelFilterBehavior": "INCLUDE",
            "labelIds": ["INBOX", "SENT"],
        }
        return await self._post("/users/me/watch", json=body)

    async def stop_watch(self) -> None:
        """`users.stop` — tear down the Pub/Sub subscription. Gmail
        responds 204; calling on a non-watching mailbox is a no-op
        (Gmail also returns 204)."""
        await self._post("/users/me/stop", json={}, expect_json=False)

    # --- private -------------------------------------------------------

    async def _get(
        self, path: str, *, params: Optional[dict] = None
    ) -> dict:
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        *,
        json: dict,
        expect_json: bool = True,
    ) -> dict:
        return await self._request(
            "POST", path, json=json, expect_json=expect_json
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        expect_json: bool = True,
    ) -> dict:
        access_token = await self._access_token()
        url = f"{_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        try:
            if self._http is not None:
                response = await self._http.request(
                    method, url, headers=headers, params=params, json=json
                )
            else:
                async with httpx.AsyncClient(
                    timeout=_HTTP_TIMEOUT
                ) as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json,
                    )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise GmailHTTPError(0, f"transport error: {exc}") from exc

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {"raw": response.text[:300]}
            raise GmailHTTPError(response.status_code, body)
        if not expect_json:
            return {}
        try:
            return response.json() or {}
        except ValueError:
            return {}

    async def _access_token(self) -> str:
        """Refresh-if-expired, then decrypt + return plaintext."""
        tokens = await email_service.refresh_if_expired(
            self._session, account=self._account
        )
        return tokens.access_token


__all__ = ["GmailClient", "GmailHTTPError"]
