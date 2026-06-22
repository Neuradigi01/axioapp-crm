"""whatsapp-platform-upgrade Step 7 — reply/quote + reactions tests.

Covers the adapter surface only (pure-Python, no DB, no FastAPI):

  * Outbound text with ``reply_to_channel_message_id`` builds a
    Meta envelope with ``context: {message_id}``.
  * Outbound ``send_reaction`` builds Meta's reaction envelope.
  * Outbound ``send_reaction(emoji=None)`` sends empty string ("remove
    my reaction" per Meta's docs).
  * Inbound text reply parses Meta's ``context.id`` onto the parsed
    message's ``reply_to_channel_message_id`` field.
  * Inbound reaction event populates the parser's ``reaction`` block
    with the target wamid + emoji + reactor's phone.
  * Inbound reaction-remove event surfaces an empty ``emoji`` so the
    service can clear the actor's row from ``reactions`` JSONB.

The service-layer behaviour (FK resolution, `_merge_reaction`,
`_apply_inbound_reaction`) is exercised end-to-end by the existing
conversations-CRUD integration tests once the migration lands; the
adapter is the boundary worth testing in isolation.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter


_PHONE_ID = "12345"
_TOKEN = "EAA_test_token"
_API_VERSION = "v19.0"
_TO = "+919876543210"
_ORG_ID = uuid.uuid4()


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
    """Capture-only httpx factory — every POST returns 200 with the
    canned ``messages[]`` echo. ``factory.calls`` carries the sent
    envelopes for assertions."""

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
                json=body
                if body is not None
                else {"messages": [{"id": "wamid.reply"}]},
            )

    factory = lambda: _Client()  # noqa: E731
    factory.calls = calls  # type: ignore[attr-defined]
    return factory


# --- outbound -----------------------------------------------------------


class TestOutboundReplyAndReaction:
    @pytest.mark.asyncio
    async def test_text_with_reply_to_carries_context_block(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send(
            org_id=_ORG_ID,
            external_id=_TO,
            text="Sure",
            attachments=[],
            reply_to_channel_message_id="wamid.original",
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "text"
        assert envelope["text"] == {"body": "Sure"}
        assert envelope["context"] == {"message_id": "wamid.original"}

    @pytest.mark.asyncio
    async def test_reaction_envelope_shape(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send_reaction(
            external_id=_TO,
            target_channel_message_id="wamid.target",
            emoji="👍",
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        assert envelope["type"] == "reaction"
        assert envelope["reaction"] == {
            "message_id": "wamid.target",
            "emoji": "👍",
        }

    @pytest.mark.asyncio
    async def test_reaction_remove_sends_empty_emoji(self):
        factory = _stub_factory()
        adapter = _adapter(factory)
        await adapter.send_reaction(
            external_id=_TO,
            target_channel_message_id="wamid.target",
            emoji=None,
        )
        envelope = factory.calls[0]["json"]  # type: ignore[attr-defined]
        # Meta's documented "remove" path: same envelope, empty emoji.
        assert envelope["reaction"]["emoji"] == ""


# --- inbound parse ------------------------------------------------------


def _inbound_envelope(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry": [
            {"changes": [{"value": {"messages": [message]}}]}
        ]
    }


class TestInboundReplyAndReactionParse:
    def test_text_reply_surfaces_context_id(self):
        adapter = _adapter(_stub_factory())
        parsed = adapter.parse_webhook(
            _inbound_envelope(
                {
                    "from": "919876543210",
                    "id": "wamid.text_reply",
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": "Got it"},
                    "context": {"id": "wamid.original"},
                }
            )
        )
        assert parsed.text == "Got it"
        assert parsed.reply_to_channel_message_id == "wamid.original"
        assert parsed.reaction is None

    def test_reaction_event_populates_reaction_block(self):
        adapter = _adapter(_stub_factory())
        parsed = adapter.parse_webhook(
            _inbound_envelope(
                {
                    "from": "919876543210",
                    "id": "wamid.reaction_event",
                    "timestamp": "1700000010",
                    "type": "reaction",
                    "reaction": {
                        "message_id": "wamid.original",
                        "emoji": "👍",
                    },
                }
            )
        )
        assert parsed.reaction is not None
        assert parsed.reaction["target_channel_message_id"] == "wamid.original"
        assert parsed.reaction["emoji"] == "👍"
        # `external_id` is normalised with the leading "+".
        assert parsed.reaction["reactor_external_id"] == "+919876543210"
        # Body is absent for reactions — the service short-circuits and
        # never creates a new message row.
        assert parsed.text is None

    def test_reaction_remove_event_surfaces_empty_emoji(self):
        adapter = _adapter(_stub_factory())
        parsed = adapter.parse_webhook(
            _inbound_envelope(
                {
                    "from": "919876543210",
                    "id": "wamid.reaction_remove",
                    "timestamp": "1700000020",
                    "type": "reaction",
                    "reaction": {
                        "message_id": "wamid.original",
                        "emoji": "",
                    },
                }
            )
        )
        assert parsed.reaction is not None
        assert parsed.reaction["target_channel_message_id"] == "wamid.original"
        assert parsed.reaction["emoji"] == ""


# --- service-layer helper -----------------------------------------------


class TestMergeReaction:
    def test_merge_appends_new_actor(self):
        from datetime import datetime, timezone
        from src.app.core.conversations.service import _merge_reaction

        rows = _merge_reaction(
            [],
            actor="user-1",
            emoji="👍",
            ts=datetime(2026, 6, 22, tzinfo=timezone.utc),
        )
        assert len(rows) == 1
        assert rows[0]["actor"] == "user-1"
        assert rows[0]["emoji"] == "👍"

    def test_merge_replaces_same_actor(self):
        from datetime import datetime, timezone
        from src.app.core.conversations.service import _merge_reaction

        existing = [{"actor": "user-1", "emoji": "👍", "ts": "old"}]
        rows = _merge_reaction(
            existing,
            actor="user-1",
            emoji="❤️",
            ts=datetime(2026, 6, 22, tzinfo=timezone.utc),
        )
        assert len(rows) == 1
        assert rows[0]["emoji"] == "❤️"

    def test_merge_removes_on_empty_emoji(self):
        from datetime import datetime, timezone
        from src.app.core.conversations.service import _merge_reaction

        existing = [
            {"actor": "user-1", "emoji": "👍", "ts": "old"},
            {"actor": "user-2", "emoji": "❤️", "ts": "old"},
        ]
        rows = _merge_reaction(
            existing,
            actor="user-1",
            emoji=None,
            ts=datetime(2026, 6, 22, tzinfo=timezone.utc),
        )
        actors = [r["actor"] for r in rows]
        assert actors == ["user-2"]
