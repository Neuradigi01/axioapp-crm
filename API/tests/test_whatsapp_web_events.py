"""Step 6 — events handlers + dispatcher tests.

Uses a fake AsyncSession + monkey-patches around the conversations
engine + audit so we exercise the routing + DB-update path without a
real database. The conversations engine integration is verified via
``receive_webhook`` call assertion (we don't re-test the engine here).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp_web import events
from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession
from src.app.core.integrations.whatsapp_web.sse_hub import hub


_ORG = uuid.uuid4()
_INTEGRATION_ID = uuid.uuid4()


def _session_row(status: str = "pending", phone: str | None = None) -> WhatsAppWebSession:
    return WhatsAppWebSession(
        id=uuid.uuid4(),
        org_id=_ORG,
        integration_id=_INTEGRATION_ID,
        sidecar_session_id="sid-xyz",
        status=status,
        phone_number=phone,
    )


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _CapturingSession:
    """AsyncSession stand-in for the events tests."""

    def __init__(self, *, integration: Optional[Integration] = None) -> None:
        self.integration = integration
        self.session_row = _session_row()
        self.commits = 0
        self.executes: list[Any] = []
        self.gets: list[Any] = []

    async def execute(self, stmt: Any) -> Any:
        self.executes.append(stmt)
        compiled = str(stmt).lower()
        if "tbl_whatsapp_web_sessions" in compiled:
            return _FakeResult(self.session_row)
        return _FakeResult(None)

    async def get(self, model: Any, pk: Any) -> Any:
        self.gets.append((model, pk))
        if model is Integration:
            return self.integration
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass

    async def refresh(self, _row: Any) -> None:
        pass

    def add(self, _row: Any) -> None:  # pragma: no cover
        pass

    async def delete(self, _row: Any) -> None:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _silence_audit() -> None:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    with patch("src.app.core.integrations.whatsapp_web.events.audit") as m:
        m.log = _noop
        yield m


@pytest.fixture(autouse=True)
def _capture_hub() -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    original_publish = hub.publish

    def _publish(integration_id: uuid.UUID, payload: dict[str, Any]) -> int:
        captured.append({"integration_id": integration_id, "payload": payload})
        return 0  # no real subscribers in unit tests

    hub.publish = _publish  # type: ignore[method-assign]
    try:
        yield captured
    finally:
        hub.publish = original_publish  # type: ignore[method-assign]


# --- translator tests -----------------------------------------------------


class TestTranslator:
    def test_text_message_maps_cleanly(self) -> None:
        out = events.to_inbound_message(
            {
                "type": "message.received",
                "session_id": "sid",
                "org_id": str(_ORG),
                "provider_message_id": "MSG_1",
                "from": "919999",
                "chat_jid": "919999@s.whatsapp.net",
                "from_me": False,
                "timestamp": "2026-06-30T08:00:00.000Z",
                "message_type": "text",
                "text": "hi",
                "raw": {"conversation": "hi"},
            }
        )
        assert out is not None
        assert out.external_id == "919999"
        assert out.text == "hi"
        assert out.channel_message_id == "MSG_1"
        assert out.attachments == []
        assert out.reaction is None
        assert out.sent_at == datetime(2026, 6, 30, 8, 0, tzinfo=UTC)

    def test_image_message_includes_attachment(self) -> None:
        out = events.to_inbound_message(
            {
                "from": "919999",
                "chat_jid": "919999@s.whatsapp.net",
                "provider_message_id": "MSG_2",
                "message_type": "image",
                "text": "smile",
                "media": {"mime_type": "image/jpeg", "size_bytes": 12345, "sha256": "deadbeef"},
                "raw": {},
            }
        )
        assert out is not None
        assert out.text == "smile"
        assert len(out.attachments) == 1
        att = out.attachments[0]
        assert att["type"] == "image"
        assert att["mime_type"] == "image/jpeg"
        assert att["sha256"] == "deadbeef"

    def test_reaction_message_maps_to_reaction_block(self) -> None:
        out = events.to_inbound_message(
            {
                "from": "919999",
                "chat_jid": "919999@s.whatsapp.net",
                "provider_message_id": "MSG_R",
                "message_type": "reaction",
                "reaction": {"target_id": "MSG_TARGET", "emoji": "👍"},
                "raw": {},
            }
        )
        assert out is not None
        assert out.reaction == {
            "target_channel_message_id": "MSG_TARGET",
            "emoji": "👍",
            "reactor_external_id": "919999",
        }

    def test_missing_chat_jid_returns_none(self) -> None:
        assert events.to_inbound_message({"from": "919999"}) is None

    def test_is_group_jid(self) -> None:
        assert events.is_group_jid("123@g.us") is True
        assert events.is_group_jid("919999@s.whatsapp.net") is False
        assert events.is_group_jid(None) is False


# --- handler tests --------------------------------------------------------


class TestHandleQrUpdated:
    @pytest.mark.asyncio
    async def test_publishes_qr_to_hub_and_marks_pairing(
        self, _capture_hub: list[dict[str, Any]]
    ) -> None:
        db = _CapturingSession()
        await events.handle_qr_updated(
            db,
            session=db.session_row,
            payload={
                "type": "qr.updated",
                "qr_data_url": "data:image/png;base64,XYZ",
            },
        )
        assert db.commits >= 1
        assert db.session_row.status == "pairing"
        assert len(_capture_hub) == 1
        msg = _capture_hub[0]["payload"]
        assert msg["type"] == "qr_updated"
        assert msg["qr_data_url"] == "data:image/png;base64,XYZ"

    @pytest.mark.asyncio
    async def test_missing_qr_data_url_is_noop(
        self, _capture_hub: list[dict[str, Any]]
    ) -> None:
        db = _CapturingSession()
        await events.handle_qr_updated(
            db,
            session=db.session_row,
            payload={"type": "qr.updated"},
        )
        assert _capture_hub == []


class TestHandleConnectionOpened:
    @pytest.mark.asyncio
    async def test_marks_connected_and_promotes_integration(
        self, _capture_hub: list[dict[str, Any]]
    ) -> None:
        integration = Integration(
            id=_INTEGRATION_ID,
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.disconnected,
        )
        db = _CapturingSession(integration=integration)

        await events.handle_connection_opened(
            db,
            session=db.session_row,
            payload={
                "type": "connection.opened",
                "phone_number": "919876543210",
            },
        )
        assert db.session_row.status == "connected"
        assert db.session_row.phone_number == "919876543210"
        assert integration.status == IntegrationStatus.connected
        assert integration.account_label == "919876543210"
        assert _capture_hub[0]["payload"]["type"] == "connected"
        assert _capture_hub[0]["payload"]["phone_number"] == "919876543210"


class TestHandleConnectionLoggedOut:
    @pytest.mark.asyncio
    async def test_expires_integration_and_pushes_logged_out(
        self, _capture_hub: list[dict[str, Any]]
    ) -> None:
        integration = Integration(
            id=_INTEGRATION_ID,
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.connected,
        )
        db = _CapturingSession(integration=integration)

        await events.handle_connection_logged_out(
            db,
            session=db.session_row,
            payload={
                "type": "connection.logged_out",
                "reason": "loggedOut",
            },
        )
        assert db.session_row.status == "logged_out"
        assert integration.status == IntegrationStatus.expired
        assert _capture_hub[0]["payload"]["type"] == "logged_out"


class TestHandleConnectionReconnecting:
    @pytest.mark.asyncio
    async def test_publishes_reconnecting_no_audit_noise(
        self,
        _capture_hub: list[dict[str, Any]],
        _silence_audit: Any,
    ) -> None:
        db = _CapturingSession()
        await events.handle_connection_reconnecting(
            db,
            session=db.session_row,
            payload={
                "type": "connection.reconnecting",
                "attempt": 2,
            },
        )
        assert db.session_row.status == "reconnecting"
        assert _capture_hub[0]["payload"]["attempt"] == 2


class TestHandleMessageReceived:
    @pytest.mark.asyncio
    async def test_group_message_is_silently_dropped(
        self, _capture_hub: list[dict[str, Any]]
    ) -> None:
        db = _CapturingSession()
        with patch(
            "src.app.core.integrations.whatsapp_web.events.conversations_service.receive_webhook"
        ) as receive:
            await events.handle_message_received(
                db,
                session=db.session_row,
                payload={
                    "type": "message.received",
                    "from": "999",
                    "chat_jid": "12345@g.us",
                    "message_type": "text",
                    "text": "yo",
                    "raw": {},
                },
            )
        receive.assert_not_called()

    @pytest.mark.asyncio
    async def test_text_message_flows_into_conversations_engine(self) -> None:
        db = _CapturingSession()
        db.session_row.phone_number = "919876543210"
        with patch(
            "src.app.core.integrations.whatsapp_web.events.conversations_service.receive_webhook",
            new_callable=AsyncMock,
        ) as receive:
            await events.handle_message_received(
                db,
                session=db.session_row,
                payload={
                    "type": "message.received",
                    "from": "919999",
                    "chat_jid": "919999@s.whatsapp.net",
                    "provider_message_id": "MSG_1",
                    "message_type": "text",
                    "text": "hi",
                    "raw": {"conversation": "hi"},
                },
            )
        receive.assert_awaited_once()
        kwargs = receive.await_args.kwargs
        assert kwargs["channel"].value == "whatsapp"
        assert kwargs["received_via_phone_id"] == "919876543210"
        assert kwargs["pre_parsed"].text == "hi"
        assert kwargs["pre_parsed"].channel_message_id == "MSG_1"

    @pytest.mark.asyncio
    async def test_engine_failure_is_swallowed(self) -> None:
        db = _CapturingSession()
        with patch(
            "src.app.core.integrations.whatsapp_web.events.conversations_service.receive_webhook",
            side_effect=RuntimeError("engine crashed"),
        ):
            # Must NOT raise — sidecar would otherwise retry + duplicate.
            await events.handle_message_received(
                db,
                session=db.session_row,
                payload={
                    "from": "919999",
                    "chat_jid": "919999@s.whatsapp.net",
                    "message_type": "text",
                    "text": "hi",
                    "raw": {},
                },
            )


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_unknown_type_returns_false(self) -> None:
        db = _CapturingSession()
        handled = await events.dispatch_event(
            db,
            session=db.session_row,
            payload={"type": "totally.unknown"},
        )
        assert handled is False

    @pytest.mark.asyncio
    async def test_known_type_calls_handler(self) -> None:
        db = _CapturingSession()
        with patch(
            "src.app.core.integrations.whatsapp_web.events.handle_qr_updated",
            new_callable=AsyncMock,
        ) as handler:
            events._HANDLERS["qr.updated"] = handler  # type: ignore[attr-defined]
            try:
                handled = await events.dispatch_event(
                    db,
                    session=db.session_row,
                    payload={"type": "qr.updated", "qr_data_url": "data:..."},
                )
            finally:
                events._HANDLERS["qr.updated"] = (  # type: ignore[attr-defined]
                    events.handle_qr_updated
                )
        assert handled is True
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_exception_swallowed_by_dispatcher(self) -> None:
        db = _CapturingSession()
        async def boom(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("intentional")

        events._HANDLERS["qr.updated"] = boom  # type: ignore[attr-defined]
        try:
            handled = await events.dispatch_event(
                db,
                session=db.session_row,
                payload={"type": "qr.updated"},
            )
        finally:
            events._HANDLERS["qr.updated"] = (  # type: ignore[attr-defined]
                events.handle_qr_updated
            )
        # Dispatcher returns True (handler fired, even if it errored).
        assert handled is True
