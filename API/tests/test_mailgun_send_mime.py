"""Coverage for :meth:`MailgunApiClient.send_mime` (Step 5a).

Uses an ``httpx.MockTransport`` handler (same shape as
:mod:`test_email_sending_domains_step2_mailgun_api_client`) so retry
policy, multipart encoding, and response parsing all exercise the
real code paths without any external network dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.app.core.email.mailgun.api_client import (
    MailgunApiClient,
    MailgunSendResult,
)
from src.app.core.email.mailgun.api_client_errors import (
    MailgunAuthError,
    MailgunProviderError,
    MailgunResponseInvalid,
)

# ---------------------------------------------------------------------------
# Helpers (mirror the Step 2 test-file _Handler pattern)
# ---------------------------------------------------------------------------


class _Handler:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.queue: list[Callable[[httpx.Request], httpx.Response]] = []

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
            content_type_headers = {
                "Content-Type": "application/json",
                **content_type_headers,
            }

        def _responder(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=status, text=text, headers=content_type_headers)

        self.queue.append(_responder)

    def as_transport(self) -> httpx.MockTransport:
        async def _handle(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            if not self.queue:
                raise AssertionError(f"unexpected mailgun request {req.method} {req.url}")
            return self.queue.pop(0)(req)

        return httpx.MockTransport(_handle)


def _client(handler: _Handler, region: str = "us") -> MailgunApiClient:
    return MailgunApiClient(region=region, transport=handler.as_transport())


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("MAILGUN_API_KEY", "test-key-abcdef")


def _accepted_body(
    *,
    raw_id: str = "<abc123xyz@example.mailgun.org>",
    message: str = "Queued. Thank you.",
) -> dict[str, Any]:
    return {"id": raw_id, "message": message}


# ---------------------------------------------------------------------------
# 1. Endpoint + multipart shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mime_posts_to_domain_messages_mime_endpoint():
    handler = _Handler()
    handler.enqueue_status(200, body=_accepted_body())
    client = _client(handler)
    await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=b"From: a@b.c\r\nTo: rcpt@customer.example\r\n\r\nhi",
    )
    req = handler.requests[0]
    assert req.method == "POST"
    assert req.url.path == "/v3/send.example/messages.mime"


@pytest.mark.asyncio
async def test_send_mime_uploads_raw_mime_as_message_file_field():
    handler = _Handler()
    handler.enqueue_status(200, body=_accepted_body())
    client = _client(handler)
    mime = b"From: a@b.c\r\nTo: rcpt@customer.example\r\nSubject: hi\r\n\r\nhello"
    await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=mime,
    )
    req = handler.requests[0]
    # httpx sets Content-Type: multipart/form-data with a random boundary.
    content_type = req.headers.get("Content-Type", "")
    assert content_type.startswith("multipart/form-data"), content_type
    # The raw MIME must appear intact somewhere in the multipart body —
    # Mailgun's contract is that the ``message`` field carries the
    # original bytes without transformation.
    assert mime in req.content


# ---------------------------------------------------------------------------
# 2. Response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mime_returns_parsed_result_with_bare_message_id():
    handler = _Handler()
    handler.enqueue_status(200, body=_accepted_body(raw_id="<abc123@x.mailgun.org>"))
    client = _client(handler)
    result = await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=b"minimal",
    )
    assert isinstance(result, MailgunSendResult)
    # Angle brackets stripped — matches the shape our channel_message_id
    # column stores elsewhere.
    assert result.mailgun_message_id == "abc123@x.mailgun.org"
    assert result.message == "Queued. Thank you."


@pytest.mark.asyncio
async def test_send_mime_malformed_response_raises_invalid():
    """Missing ``id`` key → :class:`MailgunResponseInvalid`."""
    handler = _Handler()
    handler.enqueue_status(200, body={"only_message": "Queued."})
    client = _client(handler)
    with pytest.raises(MailgunResponseInvalid):
        await client.send_mime(
            "send.example",
            to="rcpt@customer.example",
            raw_mime=b"minimal",
        )


# ---------------------------------------------------------------------------
# 3. Form fields (tags, tracking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mime_tags_and_tracking_form_fields_appear_in_body():
    handler = _Handler()
    handler.enqueue_status(200, body=_accepted_body())
    client = _client(handler)
    await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=b"m",
        tags=["campaign", "welcome"],
        tracking=False,
    )
    req = handler.requests[0]
    body = req.content
    # Both o:tag values (joined comma-sep) and o:tracking=no must
    # appear in the multipart body.
    assert b"campaign,welcome" in body
    assert b'name="o:tag"' in body
    assert b"o:tracking" in body
    assert b"no" in body


@pytest.mark.asyncio
async def test_send_mime_tracking_defaults_to_yes():
    handler = _Handler()
    handler.enqueue_status(200, body=_accepted_body())
    client = _client(handler)
    await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=b"m",
    )
    req = handler.requests[0]
    assert b'name="o:tracking"' in req.content
    assert b"yes" in req.content


# ---------------------------------------------------------------------------
# 4. Auth + error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_mime_401_raises_auth_error():
    handler = _Handler()
    handler.enqueue_status(401, body="bad key")
    client = _client(handler)
    with pytest.raises(MailgunAuthError):
        await client.send_mime(
            "send.example",
            to="rcpt@customer.example",
            raw_mime=b"m",
        )


@pytest.mark.asyncio
async def test_send_mime_502_retries_and_succeeds_on_second_attempt():
    handler = _Handler()
    handler.enqueue_status(502, body="gateway")
    handler.enqueue_status(200, body=_accepted_body())
    client = _client(handler)
    result = await client.send_mime(
        "send.example",
        to="rcpt@customer.example",
        raw_mime=b"m",
    )
    assert result.mailgun_message_id == "abc123xyz@example.mailgun.org"
    # Two requests fired (initial + one retry).
    assert len(handler.requests) == 2


@pytest.mark.asyncio
async def test_send_mime_500_fails_fast_without_retry():
    handler = _Handler()
    handler.enqueue_status(500, body="server bug")
    client = _client(handler)
    with pytest.raises(MailgunProviderError):
        await client.send_mime(
            "send.example",
            to="rcpt@customer.example",
            raw_mime=b"m",
        )
    # 500 is NOT in the retryable set — one request only.
    assert len(handler.requests) == 1
