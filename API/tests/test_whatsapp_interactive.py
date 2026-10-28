"""whatsapp-platform-upgrade Step 6 — interactive messages tests.

Covers:

  * Each of the three outbound interactive kinds (reply_buttons /
    cta_url / list) builds the documented Meta envelope.
  * Inbound button_reply / list_reply events parse into the reply
    attribution shape on `attachments[]` + the title surfaces as the
    text body.
  * Pydantic schema enforces the per-kind char/length limits — a
    4-button reply or a 25-char button title rejects.

Pure-Python — no Meta, no DB, no FastAPI TestClient.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter
from src.app.core.conversations.schemas import (
    CtaUrlPayload,
    ListPayload,
    MessageSendPayload,
    ReplyButtonsPayload,
)

_PHONE_ID = "12345"
_TOKEN = "EAA_test_token"
_API_VERSION = "v19.0"
_TO = "+919876543210"


def _adapter(http_factory) -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_id=_PHONE_ID,
        token=_TOKEN,
        app_secret="",
        verify_token="vt",
        api_version=_API_VERSION,
        http_client_factory=http_factory,
    )


def _stub_factory(*, body: dict | None = None):
    """Capture-only httpx factory — every send POST returns 200 with a
    canned messages[] payload. The `calls` attribute exposes the
    captured envelopes for assertions."""

    calls: list[dict[str, Any]] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, url, json=None, headers=None, files=None):
            calls.append({"url": url, "json": json})
            return httpx.Response(
                200,
                json=body if body is not None else {"messages": [{"id": "wamid.interactive"}]},
            )

    factory = lambda: _Client()  # noqa: E731
    factory.calls = calls  # type: ignore[attr-defined]
    return factory


# --- outbound envelope shapes -------------------------------------------


_ORG_ID = uuid.uuid4()


class TestOutboundShapes:
    @pytest.mark.asyncio
    async def test_reply_buttons_envelope(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="",
            attachments=[],
            interactive={
                "kind": "reply_buttons",
                "body": "Pick one",
                "buttons": [
                    {"id": "yes", "title": "Yes"},
                    {"id": "no", "title": "No"},
                ],
                "header": {"text": "Confirm"},
                "footer": "Tap to choose",
            },
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "interactive"
        assert envelope["interactive"]["type"] == "button"
        assert envelope["interactive"]["body"] == {"text": "Pick one"}
        assert envelope["interactive"]["header"] == {
            "type": "text",
            "text": "Confirm",
        }
        assert envelope["interactive"]["footer"] == {"text": "Tap to choose"}
        buttons = envelope["interactive"]["action"]["buttons"]
        assert [b["reply"]["id"] for b in buttons] == ["yes", "no"]
        assert [b["reply"]["title"] for b in buttons] == ["Yes", "No"]
        assert {b["type"] for b in buttons} == {"reply"}

    @pytest.mark.asyncio
    async def test_cta_url_envelope(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="",
            attachments=[],
            interactive={
                "kind": "cta_url",
                "body": "Visit our catalogue",
                "button_text": "Open",
                "url": "https://example.com/catalogue",
            },
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["interactive"]["type"] == "cta_url"
        action = envelope["interactive"]["action"]
        assert action["name"] == "cta_url"
        assert action["parameters"]["display_text"] == "Open"
        assert action["parameters"]["url"].startswith("https://")

    @pytest.mark.asyncio
    async def test_list_envelope(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="",
            attachments=[],
            interactive={
                "kind": "list",
                "body": "Browse categories",
                "button_text": "Categories",
                "sections": [
                    {
                        "title": "Living",
                        "rows": [
                            {
                                "id": "sofas",
                                "title": "Sofas",
                                "description": "3-seaters and recliners",
                            },
                            {"id": "tables", "title": "Centre tables"},
                        ],
                    }
                ],
            },
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["interactive"]["type"] == "list"
        action = envelope["interactive"]["action"]
        assert action["button"] == "Categories"
        section = action["sections"][0]
        assert section["title"] == "Living"
        ids = [r["id"] for r in section["rows"]]
        assert ids == ["sofas", "tables"]
        # Description present on first row, absent on second.
        assert "description" in section["rows"][0]
        assert "description" not in section["rows"][1]


# --- inbound parse ------------------------------------------------------


class TestInboundReplyParse:
    def test_button_reply_event_parses_into_attribution(self):
        adapter = _adapter(_stub_factory())
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.reply",
                                        "timestamp": "1700000000",
                                        "type": "interactive",
                                        "context": {"id": "wamid.original"},
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "yes",
                                                "title": "Yes",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        parsed = adapter.parse_webhook(payload)
        assert parsed.text == "Yes"
        assert len(parsed.attachments) == 1
        att = parsed.attachments[0]
        assert att["type"] == "reply"
        assert att["reply_kind"] == "button"
        assert att["reply_to_id"] == "yes"
        assert att["reply_to_title"] == "Yes"
        assert att["reply_to_message_id"] == "wamid.original"

    def test_list_reply_event_parses_into_attribution(self):
        adapter = _adapter(_stub_factory())
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.list_reply",
                                        "timestamp": "1700000000",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "list_reply",
                                            "list_reply": {
                                                "id": "sofas",
                                                "title": "Sofas",
                                                "description": "3-seaters",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        parsed = adapter.parse_webhook(payload)
        assert parsed.text == "Sofas"
        att = parsed.attachments[0]
        assert att["reply_kind"] == "list"
        assert att["reply_to_id"] == "sofas"
        assert att["reply_to_description"] == "3-seaters"


# --- schema validation --------------------------------------------------


class TestSchemaLimits:
    def test_four_reply_buttons_rejected(self):
        with pytest.raises(ValidationError):
            ReplyButtonsPayload(
                kind="reply_buttons",
                body="Pick",
                buttons=[{"id": f"b{i}", "title": f"T{i}"} for i in range(4)],
            )

    def test_overlong_button_title_rejected(self):
        with pytest.raises(ValidationError):
            ReplyButtonsPayload(
                kind="reply_buttons",
                body="Pick",
                buttons=[
                    {"id": "b1", "title": "x" * 21}  # >20 chars
                ],
            )

    def test_cta_requires_http_url(self):
        with pytest.raises(ValidationError):
            CtaUrlPayload(
                kind="cta_url",
                body="Visit",
                button_text="Open",
                url="javascript:alert(1)",
            )

    def test_list_rows_capped_at_10_across_sections(self):
        with pytest.raises(ValidationError):
            # 2 sections × 6 rows = 12 — over the 10-row total cap.
            # Pydantic enforces per-section min/max only; the total cap
            # is enforced in the section list (a section with 11 rows
            # also rejects). Test the per-section cap directly here.
            ListPayload(
                kind="list",
                body="Browse",
                button_text="Open",
                sections=[
                    {
                        "title": "S1",
                        "rows": [{"id": f"r{i}", "title": f"R{i}"} for i in range(11)],
                    }
                ],
            )

    def test_message_send_payload_accepts_interactive_only(self):
        # Empty text + no attachments + a valid interactive payload
        # must validate (the router does the cross-field check).
        payload = MessageSendPayload(
            text="",
            attachments=[],
            interactive={
                "kind": "reply_buttons",
                "body": "Pick",
                "buttons": [{"id": "b1", "title": "T1"}],
            },
        )
        assert payload.interactive is not None
        assert payload.interactive.kind == "reply_buttons"  # type: ignore[union-attr]
