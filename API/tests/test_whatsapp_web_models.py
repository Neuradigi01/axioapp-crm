"""Step 4 — scaffold-level tests for the WhatsApp Web module.

These don't drive the real DB (same constraint as
``test_integrations_table.py`` — the prod-style ``async_session()``
isn't safe to reuse across pytest-asyncio fixtures). They cover the
contract: ORM imports, table name, enum membership, Pydantic
projection, and a DAL round-trip with a fake session. End-to-end
DB writes are covered by the migration smoke in Step 4's report
and by the Step 5 service tests once the connect flow lands.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.whatsapp_web import data_access
from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession
from src.app.core.integrations.whatsapp_web.router import router as ww_router
from src.app.core.integrations.whatsapp_web.schemas import (
    WhatsAppWebSessionOut,
    WhatsAppWebStatus,
)


_ORG = uuid.uuid4()
_INTEGRATION = uuid.uuid4()
_SIDECAR_ID = "11111111-1111-1111-1111-111111111111"


class TestEnumExtension:
    def test_whatsapp_web_value_present(self) -> None:
        assert IntegrationProvider.whatsapp_web.value == "whatsapp_web"

    def test_no_value_collision_with_existing(self) -> None:
        values = {p.value for p in IntegrationProvider}
        assert "whatsapp" in values
        assert "whatsapp_web" in values
        assert len(values) == len(list(IntegrationProvider))


class TestORM:
    def test_tablename_uses_tbl_prefix(self) -> None:
        assert WhatsAppWebSession.__tablename__ == "tbl_whatsapp_web_sessions"

    def test_repr_does_not_crash(self) -> None:
        row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id=_SIDECAR_ID,
            status="pending",
        )
        # __repr__ should be safe to call on a non-persisted row.
        assert "WhatsAppWebSession" in repr(row)


class TestSchemas:
    def test_status_enum_values(self) -> None:
        assert {s.value for s in WhatsAppWebStatus} == {
            "pending",
            "pairing",
            "connected",
            "reconnecting",
            "disconnected",
            "logged_out",
            "error",
        }

    def test_session_out_projection_omits_sidecar_id(self) -> None:
        now = datetime.now(timezone.utc)
        row = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id=_SIDECAR_ID,
            status="connected",
            phone_number="919876543210",
            last_event_at=now,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        dumped = WhatsAppWebSessionOut.model_validate(row).model_dump(
            mode="json"
        )
        assert "sidecar_session_id" not in dumped
        assert dumped["status"] == "connected"
        assert dumped["phone_number"] == "919876543210"


class TestRouter:
    def test_router_prefix_and_endpoints_mounted(self) -> None:
        # Step 5 added /connect, /disconnect, /status.
        # Step 6 added /events (HMAC inbound) + /qr-stream (SSE).
        assert ww_router.prefix == "/whatsapp-web"
        paths = sorted(
            getattr(r, "path", "") for r in ww_router.routes
        )
        assert paths == [
            "/whatsapp-web/connect",
            "/whatsapp-web/disconnect",
            "/whatsapp-web/events",
            "/whatsapp-web/qr-stream",
            "/whatsapp-web/status",
        ]


# --- DAL round-trip via fake session ----------------------------------


class _FakeResult:
    def __init__(self, row: Optional[WhatsAppWebSession]) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Optional[WhatsAppWebSession]:
        return self._row


class _CapturingSession:
    """Minimal AsyncSession stand-in. Captures rows passed to ``add``
    and lets ``get_session_by_integration`` return either ``None`` or
    a pre-seeded row depending on what the test sets."""

    def __init__(self, *, existing: Optional[WhatsAppWebSession] = None) -> None:
        self.existing = existing
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self.existing)

    def add(self, row: Any) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def delete(self, row: Any) -> None:
        self.deleted.append(row)


class TestDataAccess:
    @pytest.mark.asyncio
    async def test_upsert_first_call_creates_row(self) -> None:
        session = _CapturingSession(existing=None)
        row = await data_access.upsert_session(
            session,  # type: ignore[arg-type]
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id=_SIDECAR_ID,
            status="pending",
        )
        assert len(session.added) == 1
        assert row.org_id == _ORG
        assert row.integration_id == _INTEGRATION
        assert row.sidecar_session_id == _SIDECAR_ID
        assert row.status == "pending"

    @pytest.mark.asyncio
    async def test_upsert_second_call_updates_in_place(self) -> None:
        existing = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id="old-sidecar-id",
            status="pairing",
        )
        session = _CapturingSession(existing=existing)
        row = await data_access.upsert_session(
            session,  # type: ignore[arg-type]
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id="new-sidecar-id",
            status="connected",
            phone_number="919876543210",
        )
        # No new row added — mutated in place.
        assert session.added == []
        assert row is existing
        assert row.sidecar_session_id == "new-sidecar-id"
        assert row.status == "connected"
        assert row.phone_number == "919876543210"

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self) -> None:
        session = _CapturingSession(existing=None)
        removed = await data_access.delete_session(
            session,  # type: ignore[arg-type]
            integration_id=_INTEGRATION,
        )
        assert removed is False
        assert session.deleted == []

    @pytest.mark.asyncio
    async def test_delete_present_returns_true(self) -> None:
        existing = WhatsAppWebSession(
            id=uuid.uuid4(),
            org_id=_ORG,
            integration_id=_INTEGRATION,
            sidecar_session_id=_SIDECAR_ID,
            status="connected",
        )
        session = _CapturingSession(existing=existing)
        removed = await data_access.delete_session(
            session,  # type: ignore[arg-type]
            integration_id=_INTEGRATION,
        )
        assert removed is True
        assert session.deleted == [existing]
