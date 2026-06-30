"""Step 5 — service-layer tests for connect/disconnect/status.

Uses a fake AsyncSession + a stub SidecarClient to keep these as
pure unit tests (no DB, no network). Mirrors the pattern in
``test_integrations_table.py``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp_web import service
from src.app.core.integrations.whatsapp_web.exceptions import (
    AlreadyConnected,
    SidecarUnavailable,
)
from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession


_ORG = uuid.uuid4()
_ACTOR = uuid.uuid4()


class _CapturingSession:
    """AsyncSession stand-in. ``execute`` returns a configurable row
    based on the table being queried — the test seeds it via
    ``seed_integration`` / ``seed_session``."""

    def __init__(
        self,
        *,
        integration: Optional[Integration] = None,
        session_row: Optional[WhatsAppWebSession] = None,
    ) -> None:
        self.integration = integration
        self.session_row = session_row
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0
        self.flushes = 0
        self.refreshes = 0

    async def execute(self, stmt: Any) -> Any:
        compiled = str(stmt).lower()
        if "tbl_whatsapp_web_sessions" in compiled:
            target = self.session_row
        else:
            target = self.integration

        class _R:
            def __init__(self, row: Any) -> None:
                self._row = row

            def scalar_one_or_none(self) -> Any:
                return self._row

        return _R(target)

    def add(self, row: Any) -> None:
        self.added.append(row)
        if isinstance(row, Integration) and row.id is None:
            row.id = uuid.uuid4()
            self.integration = row
        if isinstance(row, WhatsAppWebSession) and row.id is None:
            row.id = uuid.uuid4()
            self.session_row = row

    async def delete(self, row: Any) -> None:
        self.deleted.append(row)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1
        # Mirror real SQLAlchemy: a freshly-added row gets its
        # server-side default values populated on flush.
        for row in self.added:
            if isinstance(row, Integration) and row.id is None:
                row.id = uuid.uuid4()
            if isinstance(row, WhatsAppWebSession):
                if row.id is None:
                    row.id = uuid.uuid4()
                if row.created_at is None:
                    row.created_at = datetime.now(UTC)
                if row.updated_at is None:
                    row.updated_at = datetime.now(UTC)

    async def refresh(self, row: Any) -> None:
        self.refreshes += 1


@pytest.fixture(autouse=True)
def _tenant_context() -> None:
    """Service uses ``get_context().org_id`` — patch it."""
    with patch(
        "src.app.core.integrations.whatsapp_web.service.get_context"
    ) as m:
        m.return_value.org_id = _ORG
        yield


@pytest.fixture(autouse=True)
def _silence_audit() -> None:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    with patch(
        "src.app.core.integrations.whatsapp_web.service.audit"
    ) as m:
        m.log = _noop
        yield m


def _stub_client(**method_returns: Any) -> AsyncMock:
    """Build a SidecarClient stand-in with awaitable methods."""
    client = AsyncMock()
    for name, value in method_returns.items():
        setattr(client, name, AsyncMock(return_value=value))
    return client


class TestConnect:
    @pytest.mark.asyncio
    async def test_first_connect_creates_both_rows_and_calls_sidecar(self) -> None:
        db = _CapturingSession()
        client = _stub_client(
            create_session={"session_id": "sess-1", "status": "pairing"}
        )

        out = await service.connect_session(db, actor_id=_ACTOR, client=client)

        # One Integration + one WhatsAppWebSession were staged.
        integration_added = [r for r in db.added if isinstance(r, Integration)]
        session_added = [r for r in db.added if isinstance(r, WhatsAppWebSession)]
        assert len(integration_added) == 1
        assert len(session_added) == 1
        assert integration_added[0].provider == IntegrationProvider.whatsapp_web
        assert integration_added[0].status == IntegrationStatus.connected
        assert integration_added[0].connected_by == _ACTOR
        assert session_added[0].status == "pairing"
        assert session_added[0].integration_id == integration_added[0].id
        assert session_added[0].org_id == _ORG
        # Sidecar received the call with the freshly minted session id.
        client.create_session.assert_awaited_once()
        kwargs = client.create_session.await_args.kwargs
        assert kwargs["org_id"] == str(_ORG)
        assert kwargs["sidecar_session_id"] == session_added[0].sidecar_session_id
        # Output projection carries the expected status.
        assert out.status.value == "pairing"

    @pytest.mark.asyncio
    async def test_already_connected_raises(self) -> None:
        integration = Integration(
            id=uuid.uuid4(),
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.connected,
        )
        session_row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=integration.id,
            sidecar_session_id="old",
            status="connected",
        )
        db = _CapturingSession(integration=integration, session_row=session_row)
        client = _stub_client(create_session={})

        with pytest.raises(AlreadyConnected):
            await service.connect_session(db, actor_id=_ACTOR, client=client)
        client.create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_sidecar_unavailable_marks_session_error_and_reraises(
        self,
    ) -> None:
        db = _CapturingSession()
        client = AsyncMock()
        client.create_session = AsyncMock(
            side_effect=SidecarUnavailable("sidecar down", status_code=503)
        )

        with pytest.raises(SidecarUnavailable):
            await service.connect_session(db, actor_id=_ACTOR, client=client)

        session_row = next(
            r for r in db.added if isinstance(r, WhatsAppWebSession)
        )
        integration = next(r for r in db.added if isinstance(r, Integration))
        assert session_row.status == "error"
        assert "sidecar down" in (session_row.last_error or "")
        assert integration.last_error is not None
        # Local state still committed so the error is observable.
        assert db.commits >= 1


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_integration(self) -> None:
        db = _CapturingSession()
        client = _stub_client(delete_session=True)
        ok = await service.disconnect_session(
            db, actor_id=_ACTOR, client=client
        )
        assert ok is False
        client.delete_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleans_local_state_even_when_sidecar_502s(self) -> None:
        integration = Integration(
            id=uuid.uuid4(),
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.connected,
        )
        session_row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=integration.id,
            sidecar_session_id="sess-XYZ",
            status="connected",
            phone_number="91999",
        )
        db = _CapturingSession(integration=integration, session_row=session_row)
        client = AsyncMock()
        client.delete_session = AsyncMock(
            side_effect=SidecarUnavailable("sidecar down")
        )

        ok = await service.disconnect_session(
            db, actor_id=_ACTOR, client=client
        )
        assert ok is True
        assert integration.status == IntegrationStatus.disconnected
        assert integration.disconnected_by == _ACTOR
        assert session_row.status == "disconnected"
        assert session_row.phone_number is None


class TestStatus:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_integration(self) -> None:
        db = _CapturingSession()
        client = _stub_client()
        assert await service.get_status(db, client=client) is None

    @pytest.mark.asyncio
    async def test_returns_view_when_session_exists(self) -> None:
        integration = Integration(
            id=uuid.uuid4(),
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.connected,
        )
        now = datetime.now(UTC)
        session_row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=integration.id,
            sidecar_session_id="sess-XYZ",
            status="connected",
            phone_number="91999",
            last_event_at=now,
            created_at=now,
            updated_at=now,
        )
        db = _CapturingSession(integration=integration, session_row=session_row)
        client = _stub_client()

        out = await service.get_status(db, client=client)
        assert out is not None
        assert out.status.value == "connected"
        assert out.phone_number == "91999"
        client.get_session.assert_not_called()  # cached, fresh

    @pytest.mark.asyncio
    async def test_stale_connected_row_triggers_sidecar_refresh(self) -> None:
        integration = Integration(
            id=uuid.uuid4(),
            org_id=_ORG,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.connected,
        )
        stale = datetime.now(UTC) - timedelta(seconds=300)
        session_row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=integration.id,
            sidecar_session_id="sess-XYZ",
            status="connected",
            phone_number="91999",
            last_event_at=stale,
            created_at=stale,
            updated_at=stale,
        )
        db = _CapturingSession(integration=integration, session_row=session_row)
        client = _stub_client(
            get_session={
                "session_id": "sess-XYZ",
                "status": "reconnecting",
                "paired": True,
                "phone_number": "91999",
            }
        )

        out = await service.get_status(db, client=client)
        assert out is not None
        client.get_session.assert_awaited_once_with(
            sidecar_session_id="sess-XYZ"
        )
        # Mapped sidecar status flowed back into the row + projection.
        assert session_row.status == "reconnecting"
        assert out.status.value == "reconnecting"
