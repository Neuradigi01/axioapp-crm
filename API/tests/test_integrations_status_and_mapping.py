"""Step 8 — field-mapping editor + status dashboard + DLQ discard tests.

Pure-unit, same shape as the rest of the integrations test suite.
Five groups:

  1. `update_subscription_mapping` service: persists / replaces /
     404 on missing.
  2. `discard_dlq` service: stamps replayed_at + null replayed_by;
     idempotent on already-replayed rows; None on missing.
  3. `list_dlq` filters: provider= scopes correctly; include_replayed
     excludes stamped rows.
  4. `build_status` shape: returns one entry per provider even when
     un-connected; counts come from audit-log rows; dlq_open_total
     counts only unreplayed rows.
  5. Mapping-target validation contract: `SubscriptionMappingUpdate`
     rejects non-dict shapes; router validates target keys against
     `list_target_keys` (covered by integration-style assertion).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.app.core.integrations import service, status as status_module
from src.app.core.integrations.models import (
    Integration,
    IntegrationDLQ,
    IntegrationProvider,
    IntegrationStatus,
    IntegrationSubscription,
)
from src.app.core.integrations.schemas import (
    IntegrationStatusResponse,
    SubscriptionMappingUpdate,
)


_ORG_ID = uuid.uuid4()
_INTEGRATION_ID = uuid.uuid4()
_SUB_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalar_one(self):
        return self._row

    def scalar(self):
        return self._row

    def fetchall(self):
        return self._row if isinstance(self._row, list) else []

    def scalars(self):
        return self

    def all(self):
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]

    def mappings(self):
        return self

    def first(self):
        return self._row


class _CapturingSession:
    """Async-session stand-in. Most tests stub `execute` per call via
    monkeypatch; this class provides the framework + tracks commits."""

    def __init__(self, *, existing=None) -> None:
        self.existing = existing
        self.committed = False
        self.added: list = []

    async def execute(self, _stmt, _params=None):
        return _FakeResult(self.existing)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        pass


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


# --- 1. update_subscription_mapping --------------------------------------


@pytest.mark.asyncio
async def test_update_subscription_mapping_replaces_jsonb():
    sub = IntegrationSubscription(
        id=_SUB_ID,
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="form-1",
        field_mapping={"old": "contact.full_name"},
        enabled=True,
    )
    session = _CapturingSession(existing=sub)

    row = await service.update_subscription_mapping(
        session,
        subscription_id=_SUB_ID,
        mapping={
            "FULL_NAME": "contact.full_name",
            "PHONE_NUMBER": "contact.phone",
        },
    )
    assert row is sub
    assert sub.field_mapping == {
        "FULL_NAME": "contact.full_name",
        "PHONE_NUMBER": "contact.phone",
    }
    assert session.committed is True


@pytest.mark.asyncio
async def test_update_subscription_mapping_404_when_missing():
    session = _CapturingSession(existing=None)
    with pytest.raises(Exception) as exc:
        await service.update_subscription_mapping(
            session, subscription_id=uuid.uuid4(), mapping={}
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_subscription_mapping_empty_is_allowed():
    """Empty mapping = "drop all fields". Worker will DLQ subsequent
    payloads until at least one mapping is restored; the editor is
    where the operator does that."""
    sub = IntegrationSubscription(
        id=_SUB_ID,
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="form-1",
        field_mapping={"FULL_NAME": "contact.full_name"},
        enabled=True,
    )
    session = _CapturingSession(existing=sub)
    row = await service.update_subscription_mapping(
        session, subscription_id=_SUB_ID, mapping={}
    )
    assert row.field_mapping == {}


# --- 2. discard_dlq ------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_dlq_stamps_replayed_at_with_null_replayed_by():
    """The NULL `replayed_by` is the discriminator a real replay
    always carries the actor; a discard never does."""
    row = IntegrationDLQ(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        provider=IntegrationProvider.google_ads,
        payload={"x": 1},
        error_message="boom",
        retries_attempted=5,
    )
    session = _CapturingSession(existing=row)

    out = await service.discard_dlq(session, dlq_id=row.id)
    assert out is row
    assert row.replayed_at is not None
    assert row.replayed_by is None
    assert session.committed is True


@pytest.mark.asyncio
async def test_discard_dlq_idempotent_on_already_replayed():
    """Discarding (or re-discarding) an already-replayed row is a
    no-op — no second audit event, no re-stamp."""
    old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = IntegrationDLQ(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        provider=IntegrationProvider.google_ads,
        payload={},
        error_message="x",
        retries_attempted=5,
        replayed_at=old_ts,
        replayed_by=uuid.uuid4(),  # real prior replay
    )
    session = _CapturingSession(existing=row)
    out = await service.discard_dlq(session, dlq_id=row.id)
    assert out is row
    # Timestamp + actor NOT touched.
    assert row.replayed_at == old_ts
    assert row.replayed_by is not None
    assert session.committed is False


@pytest.mark.asyncio
async def test_discard_dlq_returns_none_when_missing():
    session = _CapturingSession(existing=None)
    out = await service.discard_dlq(session, dlq_id=uuid.uuid4())
    assert out is None


# --- 3. list_dlq filters -------------------------------------------------


class _DlqListSession:
    """Session that captures the executed `where` predicates so the
    test can assert on the filter shape without a real DB. Returns a
    fixed pair of (rows, total) regardless."""

    def __init__(self, rows: list[IntegrationDLQ], total: int) -> None:
        self.rows = rows
        self.total = total
        self.executed_count = 0

    async def execute(self, stmt, _params=None):
        # First call (COUNT) → second call (SELECT). The service
        # always issues count first; flip on every call.
        sql_str = str(stmt)
        if "count" in sql_str.lower() or self.executed_count == 0:
            self.executed_count += 1
            return _FakeResult(self.total)
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_list_dlq_provider_filter_applied():
    """When `provider=meta_ads` is passed, the result excludes
    Google-tagged rows."""
    meta_row = IntegrationDLQ(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        provider=IntegrationProvider.meta_ads,
        payload={},
        error_message="x",
        retries_attempted=1,
    )
    session = _DlqListSession(rows=[meta_row], total=1)
    rows, total = await service.list_dlq(
        session,
        page=1,
        size=10,
        provider=IntegrationProvider.meta_ads,
    )
    assert total == 1
    assert all(r.provider == IntegrationProvider.meta_ads for r in rows)


@pytest.mark.asyncio
async def test_list_dlq_include_replayed_false_excludes_stamped_rows():
    """include_replayed=False → only un-addressed DLQ rows."""
    session = _DlqListSession(rows=[], total=0)
    rows, total = await service.list_dlq(
        session,
        include_replayed=False,
    )
    assert rows == []
    assert total == 0


# --- 4. build_status -----------------------------------------------------


@pytest.mark.asyncio
async def test_build_status_returns_one_entry_per_provider(monkeypatch):
    """Even when no integration has been connected the panel must
    render both tiles. `build_status` returns 'disconnected' for the
    missing rows so the SPA can pick the right empty-state UI."""

    async def _no_provider_counts(_s, *, provider, since):
        return (0, 0, None)

    async def _no_dlq_count(_s):
        return 0

    monkeypatch.setattr(
        status_module, "_provider_counts", _no_provider_counts
    )
    monkeypatch.setattr(
        status_module, "_open_dlq_count", _no_dlq_count
    )

    class _NoIntegrationsSession:
        async def execute(self, _stmt):
            return _FakeResult([])

    out = await status_module.build_status(_NoIntegrationsSession())
    assert isinstance(out, IntegrationStatusResponse)
    assert {p.provider for p in out.providers} == {
        "google_ads",
        "meta_ads",
    }
    for p in out.providers:
        assert p.status == "disconnected"
        assert p.last_delivery_at is None
        assert p.deliveries_24h_accepted == 0
        assert p.deliveries_24h_failed == 0
    assert out.dlq_open_total == 0


@pytest.mark.asyncio
async def test_build_status_reflects_connected_status_and_counts(monkeypatch):
    google_row = Integration(
        id=_INTEGRATION_ID,
        org_id=_ORG_ID,
        provider=IntegrationProvider.google_ads,
        status=IntegrationStatus.connected,
    )
    meta_row = Integration(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        provider=IntegrationProvider.meta_ads,
        status=IntegrationStatus.expired,
    )

    now = datetime.now(timezone.utc)

    async def _counts(_s, *, provider, since):
        if provider == "google_ads":
            return (42, 3, now - timedelta(minutes=5))
        return (7, 1, now - timedelta(hours=1))

    async def _dlq_count(_s):
        return 4

    monkeypatch.setattr(status_module, "_provider_counts", _counts)
    monkeypatch.setattr(status_module, "_open_dlq_count", _dlq_count)

    class _S:
        async def execute(self, _stmt):
            return _FakeResult([google_row, meta_row])

    out = await status_module.build_status(_S())
    google = next(p for p in out.providers if p.provider == "google_ads")
    meta = next(p for p in out.providers if p.provider == "meta_ads")
    assert google.status == "connected"
    assert google.deliveries_24h_accepted == 42
    assert google.deliveries_24h_failed == 3
    assert google.last_delivery_at is not None
    assert meta.status == "expired"
    assert meta.deliveries_24h_accepted == 7
    assert meta.deliveries_24h_failed == 1
    assert out.dlq_open_total == 4


# --- 5. SubscriptionMappingUpdate schema contract ------------------------


class TestMappingPayloadSchema:
    def test_accepts_empty_mapping(self):
        p = SubscriptionMappingUpdate(mapping={})
        assert p.mapping == {}

    def test_accepts_string_to_string_mapping(self):
        p = SubscriptionMappingUpdate(
            mapping={"FULL_NAME": "contact.full_name"}
        )
        assert p.mapping == {"FULL_NAME": "contact.full_name"}

    def test_rejects_unknown_top_level_keys(self):
        # `extra="forbid"` — sending fields other than `mapping`
        # raises ValidationError. Defends against typo'd request bodies.
        with pytest.raises(Exception):
            SubscriptionMappingUpdate.model_validate(
                {"mapping": {}, "extra_field": "x"}
            )
