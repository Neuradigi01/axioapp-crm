"""Coverage for Step 2 of tasks/email-sending-domains/.

Tests the Mailgun API client wrapper against a ``httpx.MockTransport``
so retry, error mapping, and response parsing exercise the real code
without any external network dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.app.core.email.mailgun.api_client import (
    BASE_URL_EU,
    BASE_URL_US,
    DomainCreateResult,
    DomainDetail,
    MailgunApiClient,
    _parse_retry_after,
)
from src.app.core.email.mailgun.api_client_errors import (
    MailgunAuthError,
    MailgunNotFound,
    MailgunProviderError,
    MailgunRateLimited,
    MailgunResponseInvalid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _domain_body(name: str = "acme.example") -> dict[str, Any]:
    """Match the DISCOVERY-NOTES §GET response envelope."""
    return {
        "domain": {
            "id": "mg-domain-abc123",
            "name": name,
            "state": "unverified",
            "type": "custom",
            "created_at": "Mon, 21 Sep 2026 00:00:00 UTC",
        },
        "sending_dns_records": [
            {
                "record_type": "TXT",
                "name": f"smtp._domainkey.{name}",
                "value": "v=DKIM1; k=rsa; p=MIIB...",
                "priority": None,
                "valid": "unknown",
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": name,
                "value": "v=spf1 include:mailgun.org ~all",
                "priority": None,
                "valid": "unknown",
                "cached": [],
                "is_active": True,
            },
        ],
        "receiving_dns_records": [
            {
                "record_type": "MX",
                "name": name,
                "value": "mxa.mailgun.org",
                "priority": "10",
                "valid": "unknown",
                "cached": [],
                "is_active": True,
            }
        ],
    }


class _Handler:
    """Programmable MockTransport handler.

    Each intercepted request pops the next response from ``queue``. If
    the queue is exhausted, raises AssertionError so tests fail loudly
    rather than sending unmocked traffic.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.queue: list[Callable[[httpx.Request], httpx.Response]] = []

    def enqueue(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        self.queue.append(responder)

    def enqueue_status(
        self,
        status: int,
        *,
        body: str | dict[str, Any] = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        text = body if isinstance(body, str) else json.dumps(body)
        content_type_headers = headers or {}
        if isinstance(body, dict):
            content_type_headers = {"Content-Type": "application/json", **content_type_headers}

        def _responder(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=status, text=text, headers=content_type_headers
            )

        self.queue.append(_responder)

    def as_transport(self) -> httpx.MockTransport:
        async def _handle(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            if not self.queue:
                raise AssertionError(
                    f"unexpected mailgun request {req.method} {req.url}"
                )
            return self.queue.pop(0)(req)

        return httpx.MockTransport(_handle)


def _client(handler: _Handler, region: str = "us") -> MailgunApiClient:
    return MailgunApiClient(region=region, transport=handler.as_transport())


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "test-key-abcdef")


# ---------------------------------------------------------------------------
# 1. Region routing
# ---------------------------------------------------------------------------


def test_client_us_region_uses_us_base_url():
    client = MailgunApiClient(region="us")
    assert client.base_url == BASE_URL_US
    assert client.base_url == "https://api.mailgun.net"


def test_client_eu_region_uses_eu_base_url():
    client = MailgunApiClient(region="eu")
    assert client.base_url == BASE_URL_EU
    assert client.base_url == "https://api.eu.mailgun.net"


def test_client_default_region_reads_env(monkeypatch):
    monkeypatch.setenv("MAILGUN_REGION", "eu")
    assert MailgunApiClient().base_url == BASE_URL_EU
    monkeypatch.setenv("MAILGUN_REGION", "us")
    assert MailgunApiClient().base_url == BASE_URL_US


def test_client_unknown_region_raises():
    with pytest.raises(ValueError):
        MailgunApiClient(region="ap")


# ---------------------------------------------------------------------------
# 2. Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_missing_api_key_raises_auth_error(monkeypatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "")
    handler = _Handler()
    client = _client(handler)
    with pytest.raises(MailgunAuthError):
        await client.get_domain("acme.example")


@pytest.mark.asyncio
async def test_client_sends_basic_auth_with_api_key():
    handler = _Handler()
    handler.enqueue_status(200, body=_domain_body())
    client = _client(handler)
    await client.get_domain("acme.example")
    req = handler.requests[0]
    # httpx basic-auth: base64(api:<key>) — decoded prefix "api:".
    assert req.headers.get("Authorization", "").startswith("Basic ")


@pytest.mark.asyncio
async def test_client_401_raises_MailgunAuthError():
    handler = _Handler()
    handler.enqueue_status(401, body="bad key")
    client = _client(handler)
    with pytest.raises(MailgunAuthError) as exc:
        await client.get_domain("acme.example")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# 3. Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_404_raises_MailgunNotFound():
    handler = _Handler()
    handler.enqueue_status(404, body="not found")
    client = _client(handler)
    with pytest.raises(MailgunNotFound):
        await client.get_domain("missing.example")


@pytest.mark.asyncio
async def test_client_429_raises_MailgunRateLimited_with_retry_after():
    handler = _Handler()
    handler.enqueue_status(
        429, body="slow down", headers={"Retry-After": "60"}
    )
    client = _client(handler)
    with pytest.raises(MailgunRateLimited) as exc:
        await client.get_domain("acme.example")
    assert exc.value.retry_after_seconds == 60


@pytest.mark.asyncio
async def test_client_500_raises_MailgunProviderError_immediately():
    """500 is NOT retried (only 502/503 are)."""
    handler = _Handler()
    handler.enqueue_status(500, body="server bug")
    client = _client(handler)
    with pytest.raises(MailgunProviderError) as exc:
        await client.get_domain("acme.example")
    assert exc.value.status_code == 500
    # No retry attempted — queue was consumed once.
    assert len(handler.requests) == 1


# ---------------------------------------------------------------------------
# 4. Retry policy — 502/503 only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_retries_on_502_then_succeeds():
    handler = _Handler()
    handler.enqueue_status(502, body="gateway")
    handler.enqueue_status(200, body=_domain_body())
    client = _client(handler)
    result = await client.get_domain("acme.example")
    assert isinstance(result, DomainDetail)
    assert len(handler.requests) == 2


@pytest.mark.asyncio
async def test_client_retries_on_503_up_to_max_then_raises():
    handler = _Handler()
    for _ in range(3):  # 1 initial + 2 retries = 3 attempts total
        handler.enqueue_status(503, body="unavailable")
    client = _client(handler)
    with pytest.raises(MailgunProviderError) as exc:
        await client.get_domain("acme.example")
    assert exc.value.status_code == 503
    assert len(handler.requests) == 3


@pytest.mark.asyncio
async def test_client_does_not_retry_4xx():
    """Every 4xx surfaces on the first response."""
    handler = _Handler()
    handler.enqueue_status(400, body="bad request")
    client = _client(handler)
    with pytest.raises(Exception):
        await client.get_domain("acme.example")
    assert len(handler.requests) == 1


# ---------------------------------------------------------------------------
# 5. Response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_domain_parses_verbatim_records():
    handler = _Handler()
    body = _domain_body("acme.example")
    handler.enqueue_status(200, body=body)
    client = _client(handler)
    result = await client.get_domain("acme.example")
    assert result.mailgun_domain_id == "mg-domain-abc123"
    assert result.name == "acme.example"
    assert result.state == "unverified"
    # Verbatim round-trip — no field renames.
    assert result.sending_dns_records == body["sending_dns_records"]
    assert result.receiving_dns_records == body["receiving_dns_records"]
    # MX record's priority preserved as string.
    assert result.receiving_dns_records[0]["priority"] == "10"


@pytest.mark.asyncio
async def test_create_domain_returns_DomainCreateResult():
    handler = _Handler()
    handler.enqueue_status(200, body=_domain_body("new.example"))
    client = _client(handler)
    result = await client.create_domain("new.example")
    assert isinstance(result, DomainCreateResult)
    assert result.name == "new.example"


@pytest.mark.asyncio
async def test_create_domain_sends_dkim_key_size_2048_default():
    handler = _Handler()
    handler.enqueue_status(200, body=_domain_body())
    client = _client(handler)
    await client.create_domain("acme.example")
    req = handler.requests[0]
    body_text = req.content.decode()
    assert "dkim_key_size=2048" in body_text
    assert "name=acme.example" in body_text


@pytest.mark.asyncio
async def test_create_domain_dkim_key_size_1024_when_requested():
    handler = _Handler()
    handler.enqueue_status(200, body=_domain_body())
    client = _client(handler)
    await client.create_domain("acme.example", dkim_key_size=1024)
    assert "dkim_key_size=1024" in handler.requests[0].content.decode()


@pytest.mark.asyncio
async def test_verify_domain_hits_verify_path():
    handler = _Handler()
    handler.enqueue_status(200, body=_domain_body())
    client = _client(handler)
    await client.verify_domain("acme.example")
    req = handler.requests[0]
    assert req.method == "PUT"
    assert req.url.path == "/v4/domains/acme.example/verify"


@pytest.mark.asyncio
async def test_delete_domain_hits_delete_path():
    handler = _Handler()
    handler.enqueue_status(200, body=json.dumps({"message": "Domain has been deleted"}))
    client = _client(handler)
    await client.delete_domain("acme.example")
    req = handler.requests[0]
    assert req.method == "DELETE"
    assert req.url.path == "/v4/domains/acme.example"


@pytest.mark.asyncio
async def test_delete_domain_404_is_treated_as_success():
    handler = _Handler()
    handler.enqueue_status(404, body="not found")
    client = _client(handler)
    # Does NOT raise — delete is idempotent.
    await client.delete_domain("already-gone.example")


# ---------------------------------------------------------------------------
# 6. Response shape validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_missing_domain_key_raises_ResponseInvalid():
    handler = _Handler()
    handler.enqueue_status(
        200,
        body={
            "sending_dns_records": [],
            "receiving_dns_records": [],
            # `domain` missing
        },
    )
    client = _client(handler)
    with pytest.raises(MailgunResponseInvalid):
        await client.get_domain("acme.example")


@pytest.mark.asyncio
async def test_response_non_json_raises_ResponseInvalid():
    handler = _Handler()
    handler.enqueue_status(200, body="<html>edge cache error</html>")
    client = _client(handler)
    with pytest.raises(MailgunResponseInvalid):
        await client.get_domain("acme.example")


# ---------------------------------------------------------------------------
# 7. Retry-After header parsing
# ---------------------------------------------------------------------------


def test_parse_retry_after_int_string():
    resp = httpx.Response(200, headers={"Retry-After": "42"})
    assert _parse_retry_after(resp) == 42


def test_parse_retry_after_missing_header():
    resp = httpx.Response(200)
    assert _parse_retry_after(resp) is None


def test_parse_retry_after_malformed_returns_none():
    resp = httpx.Response(200, headers={"Retry-After": "Mon, 01 Jan 2027"})
    assert _parse_retry_after(resp) is None
