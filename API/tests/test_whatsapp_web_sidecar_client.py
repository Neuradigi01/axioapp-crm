"""Step 5 — SidecarClient HMAC + error-mapping tests.

Uses ``httpx.MockTransport`` (stdlib-equivalent, ships with httpx) to
intercept outbound requests so we exercise the real signing path and
real status-code mapping without needing the Node sidecar running.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from src.app.core.integrations.whatsapp_web.exceptions import (
    SessionNotConnected,
    SidecarRateLimited,
    SidecarUnavailable,
)
from src.app.core.integrations.whatsapp_web.sidecar_client import (
    SIGNATURE_HEADER,
    SidecarClient,
)


_SECRET = "a" * 64
_BASE = "http://sidecar.test"


def _expected_signature(body: str, secret: str = _SECRET) -> str:
    digest = hmac.new(
        secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


class _Recorder:
    """Captures each intercepted request so assertions can inspect it."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def make_transport(self, handler) -> httpx.MockTransport:
        async def wrapper(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            return handler(req)

        return httpx.MockTransport(wrapper)


def _client(transport: httpx.MockTransport) -> SidecarClient:
    return SidecarClient(
        base_url=_BASE, hmac_secret=_SECRET, transport=transport
    )


class TestHmacSigning:
    @pytest.mark.asyncio
    async def test_post_body_signature_matches_canonical_hmac(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"session_id": "abc", "status": "pairing"}
            )

        client = _client(rec.make_transport(handler))
        await client.create_session(
            org_id="org-1", sidecar_session_id="sess-1"
        )

        assert len(rec.requests) == 1
        req = rec.requests[0]
        body = req.read().decode("utf-8")
        assert body == json.dumps(
            {"org_id": "org-1", "session_id": "sess-1"},
            separators=(",", ":"),
        )
        assert req.headers[SIGNATURE_HEADER] == _expected_signature(body)
        assert req.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_get_request_signs_empty_body(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "pairing"})

        client = _client(rec.make_transport(handler))
        await client.get_session(sidecar_session_id="sess-1")

        assert rec.requests[0].headers[SIGNATURE_HEADER] == _expected_signature("")


class TestStatusCodeMapping:
    @pytest.mark.asyncio
    async def test_2xx_returns_json_payload(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "pairing", "paired": False})

        client = _client(rec.make_transport(handler))
        out = await client.get_session(sidecar_session_id="sess-1")
        assert out == {"status": "pairing", "paired": False}

    @pytest.mark.asyncio
    async def test_404_on_get_returns_none(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "session not found"})

        client = _client(rec.make_transport(handler))
        out = await client.get_session(sidecar_session_id="missing")
        assert out is None

    @pytest.mark.asyncio
    async def test_5xx_raises_sidecar_unavailable(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="sidecar booting")

        client = _client(rec.make_transport(handler))
        with pytest.raises(SidecarUnavailable) as exc:
            await client.create_session(
                org_id="org-1", sidecar_session_id="sess-1"
            )
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited_with_retry_after(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"error": "rate_limited", "retry_after_seconds": 4},
            )

        client = _client(rec.make_transport(handler))
        with pytest.raises(SidecarRateLimited) as exc:
            await client.send_text(
                sidecar_session_id="sess-1", to="91999", body="hi"
            )
        assert exc.value.retry_after_seconds == 4

    @pytest.mark.asyncio
    async def test_409_session_not_connected_maps_to_exception(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409, json={"error": "session_not_connected", "status": "pairing"}
            )

        client = _client(rec.make_transport(handler))
        with pytest.raises(SessionNotConnected):
            await client.send_text(
                sidecar_session_id="sess-1", to="91999", body="hi"
            )

    @pytest.mark.asyncio
    async def test_network_error_maps_to_sidecar_unavailable(self) -> None:
        async def broken(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sidecar unreachable")

        transport = httpx.MockTransport(broken)
        client = _client(transport)
        with pytest.raises(SidecarUnavailable):
            await client.create_session(
                org_id="org-1", sidecar_session_id="sess-1"
            )


class TestEmptySecret:
    @pytest.mark.asyncio
    async def test_empty_secret_refuses_to_call(self) -> None:
        client = SidecarClient(
            base_url=_BASE, hmac_secret="", transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={})
            )
        )
        with pytest.raises(SidecarUnavailable, match="HMAC_SECRET"):
            await client.get_session(sidecar_session_id="sess-1")


class TestPathConstruction:
    @pytest.mark.asyncio
    async def test_session_paths_include_session_id(self) -> None:
        rec = _Recorder()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        client = _client(rec.make_transport(handler))
        await client.delete_session(sidecar_session_id="sess-XYZ")
        assert rec.requests[0].url.path == "/sessions/sess-XYZ"
        assert rec.requests[0].method == "DELETE"
