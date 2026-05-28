"""Step 3.5.5 — adapter `send_template` + `_render_template_components`.

What we prove:

  1. `_render_template_components` produces Meta's exact `components[]`
     shape (numeric ordering, type='text' parameters, header-only when
     applicable).
  2. `WhatsAppAdapter.send_template` POSTs the right envelope to Meta
     and returns a `ChannelMessageRef` on 200.
  3. Non-2xx Meta responses raise `WhatsAppSendError` with the verbatim
     status + body — caller (campaigns dispatch in 3.5.6) wraps it
     into a CampaignMessage.failed.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    WhatsAppSendError,
    _render_template_components,
)


_ORG_ID = uuid.uuid4()


# --- pure helper ---------------------------------------------------------


class TestRenderComponents:
    def test_body_only_orders_by_variable_number(self):
        out = _render_template_components(
            variables={2: "sofa set", 1: "Asha"}
        )
        assert out == [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Asha"},
                    {"type": "text", "text": "sofa set"},
                ],
            }
        ]

    def test_header_with_placeholder_emits_header_component(self):
        out = _render_template_components(
            variables={1: "Asha", 2: "30%"},
            header_type="TEXT",
            header_text="Hi {{1}}, special deal",
        )
        # Header comes first, body second.
        assert out[0] == {
            "type": "header",
            "parameters": [{"type": "text", "text": "Asha"}],
        }
        assert out[1]["type"] == "body"
        # Body still gets BOTH variables — the picker collects one input
        # per `{{n}}` regardless of where it appears in the template.
        assert len(out[1]["parameters"]) == 2

    def test_header_without_placeholder_skipped(self):
        """A header with literal text (no `{{1}}`) carries no parameter
        slot — only the body component renders."""
        out = _render_template_components(
            variables={1: "Asha"},
            header_type="TEXT",
            header_text="Welcome — static header",
        )
        assert len(out) == 1
        assert out[0]["type"] == "body"

    def test_empty_variables_returns_empty_list(self):
        out = _render_template_components(variables={})
        assert out == []

    def test_non_text_header_ignored(self):
        """IMAGE / VIDEO / DOCUMENT headers are out of scope here —
        the helper just skips them and renders body only."""
        out = _render_template_components(
            variables={1: "Asha"},
            header_type="IMAGE",
            header_text=None,
        )
        assert len(out) == 1
        assert out[0]["type"] == "body"


# --- adapter.send_template ----------------------------------------------


class _FakeHttpClient:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.last_url: str | None = None
        self.last_payload: dict | None = None
        self.last_headers: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def post(self, url, json=None, headers=None):
        self.last_url = url
        self.last_payload = json
        self.last_headers = headers
        return self._response


class TestSendTemplate:
    @pytest.mark.asyncio
    async def test_happy_path_posts_meta_envelope(self):
        meta_response = httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "messages": [{"id": "wamid.HBgM..."}],
            },
        )
        client = _FakeHttpClient(meta_response)
        adapter = WhatsAppAdapter(
            phone_id="123456789012345",
            token="dev-token",
            app_secret="dev-secret",
            verify_token="dev-verify",
            api_version="v18.0",
            http_client_factory=lambda: client,
        )

        ref = await adapter.send_template(
            org_id=_ORG_ID,
            external_id="+91 98765 43210",
            template_name="diwali_sale_2026",
            language="en_US",
            variables={1: "Asha", 2: "sofa set"},
        )

        # URL hits the messages endpoint.
        assert client.last_url == (
            "https://graph.facebook.com/v18.0/123456789012345/messages"
        )
        # Auth header carries the bearer token (NOT the env var fallback).
        assert client.last_headers["Authorization"] == "Bearer dev-token"
        # Payload is the exact Meta template envelope.
        payload = client.last_payload
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "919876543210"
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "diwali_sale_2026"
        assert payload["template"]["language"] == {"code": "en_US"}
        assert payload["template"]["components"] == [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Asha"},
                    {"type": "text", "text": "sofa set"},
                ],
            }
        ]
        # ChannelMessageRef carries Meta's message id.
        assert ref.channel_message_id == "wamid.HBgM..."

    @pytest.mark.asyncio
    async def test_meta_400_raises_send_error(self):
        meta_response = httpx.Response(
            400,
            content=json.dumps(
                {
                    "error": {
                        "message": "(#131056) Pair (phone, language) "
                        "not allowed",
                        "code": 131056,
                    }
                }
            ).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        client = _FakeHttpClient(meta_response)
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: client,
        )

        with pytest.raises(WhatsAppSendError, match="131056"):
            await adapter.send_template(
                org_id=_ORG_ID,
                external_id="+91 98765 43210",
                template_name="bogus_template",
                language="en_US",
                variables={1: "x"},
            )

    @pytest.mark.asyncio
    async def test_zero_variable_template_no_components_block(self):
        """A template with no `{{n}}` placeholders (e.g. plain
        announcement body) sends WITHOUT a `components` field —
        Meta rejects an empty `components: []`."""
        meta_response = httpx.Response(
            200, json={"messages": [{"id": "wamid.X"}]}
        )
        client = _FakeHttpClient(meta_response)
        adapter = WhatsAppAdapter(
            phone_id="123",
            token="t",
            app_secret="s",
            verify_token="v",
            api_version="v18.0",
            http_client_factory=lambda: client,
        )

        await adapter.send_template(
            org_id=_ORG_ID,
            external_id="+91 98765 43210",
            template_name="welcome",
            language="en_US",
            variables={},
        )

        payload = client.last_payload
        assert "components" not in payload["template"]
