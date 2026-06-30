"""WhatsAppAdapter.send() — assert request shape against a mocked httpx.

We don't go to the wire; the adapter is told to use a fake
`AsyncClient`-shaped object that records the call.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    WhatsAppSendError,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._status = status
        self._body = body or {"messages": [{"id": "wamid.ABC"}]}

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, *, json: Any, headers: dict) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(self._status, self._body)


def _adapter(client: _FakeAsyncClient) -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id="PHONE123",
        token="bearer-xyz",
        app_secret="s",
        verify_token="v",
        api_version="v18.0",
        http_client_factory=lambda: client,
    )


@pytest.mark.asyncio
async def test_send_posts_correct_envelope():
    client = _FakeAsyncClient()
    adapter = _adapter(client)

    ref = await adapter.send(
        org_id=uuid.uuid4(),
        external_id="+91 98765 00000",
        text="Hello WhatsApp",
        attachments=[],
    )

    assert ref.channel_message_id == "wamid.ABC"
    assert ref.sent_at is not None
    assert len(client.calls) == 1
    call = client.calls[0]
    # URL composed from api_version + phone_id
    assert call["url"] == ("https://graph.facebook.com/v18.0/PHONE123/messages")
    # Phone normalised — digits only, NO leading "+" on the wire.
    assert call["json"]["to"] == "919876500000"
    assert call["json"]["messaging_product"] == "whatsapp"
    assert call["json"]["type"] == "text"
    assert call["json"]["text"] == {"body": "Hello WhatsApp"}
    # Bearer header carries the token verbatim.
    assert call["headers"]["Authorization"] == "Bearer bearer-xyz"
    assert call["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_send_raises_on_non_2xx():
    client = _FakeAsyncClient(status=400, body={"error": "bad"})
    adapter = _adapter(client)
    with pytest.raises(WhatsAppSendError):
        await adapter.send(
            org_id=uuid.uuid4(),
            external_id="+919876500000",
            text="hi",
            attachments=[],
        )
