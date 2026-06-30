"""HMAC-signed HTTP client for the WhatsApp Web Node sidecar.

The sidecar (``sidecars/whatsapp-web/``) owns the WhatsApp Web
protocol; FastAPI calls it over HTTP and HMAC-signs every request
body. This module is the only place that knows how to talk to the
sidecar — service.py treats it as a black box.

Both secrets must match the sidecar's environment exactly:

  - ``WHATSAPP_WEB_SIDECAR_HMAC_SECRET`` ↔ sidecar's ``SIDECAR_HMAC_SECRET``
  - ``WHATSAPP_WEB_INBOUND_HMAC_SECRET`` ↔ sidecar's ``FASTAPI_HMAC_SECRET``
    (used by the Step-6 events receiver, not here)

Mismatch ⇒ sidecar returns 401 ``{"error":"invalid signature"}``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Optional

import httpx

from config import (
    WHATSAPP_WEB_SIDECAR_HMAC_SECRET,
    WHATSAPP_WEB_SIDECAR_URL,
)
from src.app.core.integrations.whatsapp_web.exceptions import (
    SessionNotConnected,
    SidecarRateLimited,
    SidecarUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
MEDIA_TIMEOUT_S = 30.0
SIGNATURE_HEADER = "X-Sidecar-Signature"


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


class SidecarClient:
    """Thin async wrapper around the sidecar's HTTP surface. One
    instance per request is fine; the underlying ``httpx.AsyncClient``
    is created lazily per call so we don't leak connections.

    A custom ``transport`` can be injected for testing — every call
    funnels through ``_request`` and uses the same transport.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        hmac_secret: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or WHATSAPP_WEB_SIDECAR_URL).rstrip("/")
        self._secret = hmac_secret or WHATSAPP_WEB_SIDECAR_HMAC_SECRET
        self._timeout = timeout
        self._transport = transport

    # --- core request helper ---------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        timeout: float | None = None,
        expect_binary: bool = False,
    ) -> httpx.Response:
        if not self._secret:
            raise SidecarUnavailable(
                "WHATSAPP_WEB_SIDECAR_HMAC_SECRET is empty — refusing to "
                "call the sidecar without an HMAC secret."
            )

        body = (
            json.dumps(payload, separators=(",", ":"))
            if payload is not None
            else ""
        )
        headers: dict[str, str] = {SIGNATURE_HEADER: _sign(body, self._secret)}
        if payload is not None:
            headers["Content-Type"] = "application/json"

        url = f"{self._base_url}{path}"
        client_kwargs: dict[str, Any] = {
            "timeout": timeout or self._timeout,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.request(
                    method,
                    url,
                    content=body if body else None,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "sidecar.request_failed",
                extra={"method": method, "path": path, "err": str(exc)},
            )
            raise SidecarUnavailable(
                f"Sidecar network error: {exc.__class__.__name__}"
            ) from exc

        if resp.status_code == 409 and not expect_binary:
            self._raise_not_connected(resp)
        if resp.status_code == 429:
            self._raise_rate_limited(resp)
        if 500 <= resp.status_code < 600:
            raise SidecarUnavailable(
                f"Sidecar returned {resp.status_code}",
                status_code=resp.status_code,
            )

        return resp

    @staticmethod
    def _raise_not_connected(resp: httpx.Response) -> None:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        raise SessionNotConnected(
            payload.get("error", "session_not_connected")
        )

    @staticmethod
    def _raise_rate_limited(resp: httpx.Response) -> None:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        retry_after = int(
            payload.get("retry_after_seconds")
            or resp.headers.get("Retry-After")
            or 1
        )
        raise SidecarRateLimited(
            payload.get("error", "rate_limited"),
            retry_after_seconds=retry_after,
        )

    # --- sessions --------------------------------------------------------

    async def create_session(
        self, *, org_id: str, sidecar_session_id: str
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            "/sessions",
            payload={"org_id": org_id, "session_id": sidecar_session_id},
        )
        if resp.status_code != 200:
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on create",
                status_code=resp.status_code,
            )
        return resp.json()

    async def get_session(self, *, sidecar_session_id: str) -> dict[str, Any] | None:
        resp = await self._request("GET", f"/sessions/{sidecar_session_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on get",
                status_code=resp.status_code,
            )
        return resp.json()

    async def delete_session(self, *, sidecar_session_id: str) -> bool:
        resp = await self._request("DELETE", f"/sessions/{sidecar_session_id}")
        if resp.status_code == 404:
            return False
        if resp.status_code not in (200, 204):
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on delete",
                status_code=resp.status_code,
            )
        return True

    # --- messages (Step 7 will use these) --------------------------------

    async def send_text(
        self,
        *,
        sidecar_session_id: str,
        to: str,
        body: str,
        reply_to: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"to": to, "body": body}
        if reply_to is not None:
            payload["reply_to"] = reply_to
        resp = await self._request(
            "POST",
            f"/sessions/{sidecar_session_id}/send-text",
            payload=payload,
        )
        if resp.status_code != 200:
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on send-text",
                status_code=resp.status_code,
            )
        return resp.json()

    async def send_media(
        self,
        *,
        sidecar_session_id: str,
        to: str,
        media_type: str,
        base64_payload: str,
        mime_type: str,
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to": to,
            "media_type": media_type,
            "base64": base64_payload,
            "mime_type": mime_type,
        }
        if filename is not None:
            payload["filename"] = filename
        if caption is not None:
            payload["caption"] = caption
        resp = await self._request(
            "POST",
            f"/sessions/{sidecar_session_id}/send-media",
            payload=payload,
            timeout=MEDIA_TIMEOUT_S,
        )
        if resp.status_code != 200:
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on send-media",
                status_code=resp.status_code,
            )
        return resp.json()

    async def download_media(
        self,
        *,
        sidecar_session_id: str,
        provider_message_id: str,
    ) -> bytes:
        resp = await self._request(
            "GET",
            f"/sessions/{sidecar_session_id}/download-media/{provider_message_id}",
            timeout=MEDIA_TIMEOUT_S,
            expect_binary=True,
        )
        if resp.status_code == 404:
            raise SidecarUnavailable(
                "media unavailable", status_code=resp.status_code
            )
        if resp.status_code != 200:
            raise SidecarUnavailable(
                f"Unexpected sidecar status {resp.status_code} on download-media",
                status_code=resp.status_code,
            )
        return resp.content


__all__ = ["SidecarClient", "SIGNATURE_HEADER"]
