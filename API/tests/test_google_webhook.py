"""Step 3 — Google Ads webhook receiver + task + DLQ tests.

Same approach as the Step-1 / Step-2 tests: pure-unit with
monkey-patched DB sessions. We don't drive the live test DB because
the prod-style `async_session()` engine isn't safe to share across
pytest-asyncio fixtures (asyncpg's "another operation in progress").
Smoke tests cover end-to-end DB writes.

Eight groups:

  1. `_extract_form_id` / `_extract_lead_id` payload helpers.
  2. `_apply_mapping` — Google's `user_column_data` array → CRM keys.
  3. `_build_attribution` — outputs the spec'd 4-key shape.
  4. Webhook receiver: 401 on unknown key, 401 on body mismatch,
     200 on happy path (with enqueue verified via monkey-patched
     `.delay`).
  5. `process_google_lead_async`: happy path, disconnected → DLQ,
     no-subscription → DLQ, missing form_id → DLQ.
  6. Idempotency: `_find_lead_by_external_id` short-circuits a
     duplicate replay.
  7. Service: `_new_webhook_secret` shape; `upsert` writes a secret;
     `disconnect` nulls it.
  8. DLQ: `replay_dlq` re-enqueues + marks replayed.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.core.integrations import service as integration_service
from src.app.core.integrations.google import dlq as dlq_module
from src.app.core.integrations.google import tasks as tasks_module
from src.app.core.integrations.google import webhook as webhook_module
from src.app.core.integrations.google.tasks import (
    _apply_mapping,
    _build_attribution,
    _extract_form_id,
    _extract_lead_id,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationDLQ,
    IntegrationProvider,
    IntegrationStatus,
    IntegrationSubscription,
)

_ORG_ID = uuid.uuid4()
_INTEGRATION_ID = uuid.uuid4()
_SECRET = "test-webhook-secret"


# --- helpers -------------------------------------------------------------


def _make_integration(
    *,
    status: IntegrationStatus = IntegrationStatus.connected,
    webhook_secret: str | None = _SECRET,
) -> Integration:
    return Integration(
        id=_INTEGRATION_ID,
        org_id=_ORG_ID,
        provider=IntegrationProvider.google_ads,
        status=status,
        webhook_secret=webhook_secret,
    )


def _make_subscription(
    *,
    field_mapping: dict | None = None,
    enabled: bool = True,
    form_id: str = "form-1",
) -> IntegrationSubscription:
    return IntegrationSubscription(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id=form_id,
        external_form_label=None,
        field_mapping=field_mapping
        or {
            "FULL_NAME": "contact.full_name",
            "PHONE_NUMBER": "contact.phone",
            "WORK_EMAIL": "contact.email",
        },
        enabled=enabled,
    )


def _sample_payload(
    *,
    form_id: str = "form-1",
    lead_id: str = "lead-abc",
    campaign_id: str = "camp-1",
    gclid: str = "gclid-xyz",
    columns: list[dict] | None = None,
    google_key: str = _SECRET,
) -> dict:
    return {
        "google_key": google_key,
        "form_id": form_id,
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "gclid": gclid,
        "user_column_data": columns
        or [
            {"column_name": "FULL_NAME", "string_value": "Asha Khan"},
            {"column_name": "PHONE_NUMBER", "string_value": "+919876543210"},
            {"column_name": "WORK_EMAIL", "string_value": "asha@example.com"},
        ],
    }


# --- 1. payload extractors ----------------------------------------------


class TestPayloadExtractors:
    def test_form_id_form_id_key(self):
        assert _extract_form_id({"form_id": "abc"}) == "abc"

    def test_form_id_fallback_to_lead_form_id(self):
        assert _extract_form_id({"lead_form_id": "xyz"}) == "xyz"

    def test_form_id_missing_returns_none(self):
        assert _extract_form_id({}) is None

    def test_lead_id_present(self):
        assert _extract_lead_id({"lead_id": "L-1"}) == "L-1"

    def test_lead_id_missing(self):
        assert _extract_lead_id({}) is None


# --- 2. field mapping ----------------------------------------------------


class TestApplyMapping:
    def test_maps_camelcase_column_keys(self):
        mapping = {"FULL_NAME": "contact.full_name"}
        out = _apply_mapping(
            mapping,
            {
                "user_column_data": [
                    {"columnName": "FULL_NAME", "stringValue": "Asha"},
                ]
            },
        )
        assert out == {"contact.full_name": "Asha"}

    def test_maps_snakecase_column_keys(self):
        mapping = {
            "FULL_NAME": "contact.full_name",
            "PHONE_NUMBER": "contact.phone",
        }
        out = _apply_mapping(
            mapping,
            {
                "user_column_data": [
                    {"column_name": "FULL_NAME", "string_value": "Asha"},
                    {"column_name": "PHONE_NUMBER", "string_value": "+91"},
                ]
            },
        )
        assert out["contact.full_name"] == "Asha"
        assert out["contact.phone"] == "+91"

    def test_drops_unmapped_columns(self):
        out = _apply_mapping(
            {"FULL_NAME": "contact.full_name"},
            {
                "user_column_data": [
                    {"column_name": "FULL_NAME", "string_value": "Asha"},
                    {"column_name": "VEHICLE_INTEREST", "string_value": "Sofa"},
                ]
            },
        )
        assert "contact.full_name" in out
        assert "lead.something" not in out
        # Unmapped column silently dropped.
        assert "VEHICLE_INTEREST" not in out

    def test_empty_when_no_user_column_data(self):
        assert _apply_mapping({"X": "y"}, {}) == {}


# --- 3. attribution ------------------------------------------------------


class TestBuildAttribution:
    def test_includes_spec_keys(self):
        attr = _build_attribution(
            {
                "form_id": "F-1",
                "lead_id": "L-1",
                "campaign_id": "C-1",
                "gclid": "G-1",
            }
        )
        assert attr["external_form_id"] == "F-1"
        assert attr["external_lead_id"] == "L-1"
        assert attr["form_id"] == "F-1"
        assert attr["lead_id"] == "L-1"
        assert attr["campaign_id"] == "C-1"
        assert attr["gclid"] == "G-1"

    def test_skips_missing_keys(self):
        attr = _build_attribution({"form_id": "F-1", "lead_id": "L-1"})
        assert "campaign_id" not in attr
        assert "gclid" not in attr
        assert attr["external_form_id"] == "F-1"


# --- 4. Webhook receiver (FastAPI + monkeypatched lookups) --------------


def _build_app() -> FastAPI:
    """Mount just the webhook router on a fresh FastAPI app — bypasses
    the full src.app.main import surface (and its lifespan) so each
    receiver test starts in a clean state."""
    app = FastAPI()
    app.include_router(webhook_module.router, prefix="/api/v1/integrations")
    return app


@pytest.mark.asyncio
async def test_receiver_401_on_unknown_webhook_key(monkeypatch):
    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module, "get_by_webhook_secret", _none)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/google/webhook/v1/garbage",
            json={"google_key": "garbage"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"] == "unknown webhook key"


@pytest.mark.asyncio
async def test_receiver_401_when_integration_disconnected(monkeypatch):
    integration = _make_integration(status=IntegrationStatus.disconnected, webhook_secret=_SECRET)

    async def _return(*_a, **_k):
        return integration

    monkeypatch.setattr(webhook_module, "get_by_webhook_secret", _return)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/integrations/google/webhook/v1/{_SECRET}",
            json={"google_key": _SECRET},
        )
    assert resp.status_code == 401
    assert "disconnected" in resp.json()["error"]


@pytest.mark.asyncio
async def test_receiver_401_on_google_key_mismatch(monkeypatch):
    integration = _make_integration()

    async def _return(*_a, **_k):
        return integration

    monkeypatch.setattr(webhook_module, "get_by_webhook_secret", _return)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/integrations/google/webhook/v1/{_SECRET}",
            json={"google_key": "WRONG_KEY"},
        )
    assert resp.status_code == 401
    assert "google_key" in resp.json()["error"]


@pytest.mark.asyncio
async def test_receiver_200_and_enqueues_on_happy_path(monkeypatch):
    integration = _make_integration()

    async def _return(*_a, **_k):
        return integration

    monkeypatch.setattr(webhook_module, "get_by_webhook_secret", _return)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    # Force the HAS_CELERY=True branch + capture the .delay call.
    captured: dict[str, Any] = {}

    class _FakeTask:
        def delay(self, *args, **_):
            captured["args"] = args

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_google_lead", _FakeTask())

    app = _build_app()
    body = _sample_payload()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/integrations/google/webhook/v1/{_SECRET}",
            json=body,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert captured["args"][0] == str(_INTEGRATION_ID)
    assert captured["args"][1]["lead_id"] == "lead-abc"


@pytest.mark.asyncio
async def test_receiver_returns_200_even_if_enqueue_raises(monkeypatch):
    """Google retries on any non-2xx. A broker-down spike must not
    cascade into a retry-storm — log and 200."""
    integration = _make_integration()

    async def _return(*_a, **_k):
        return integration

    monkeypatch.setattr(webhook_module, "get_by_webhook_secret", _return)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    class _BrokenTask:
        def delay(self, *_a, **_k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_google_lead", _BrokenTask())

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/integrations/google/webhook/v1/{_SECRET}",
            json=_sample_payload(),
        )
    assert resp.status_code == 200


# --- 5. process_google_lead_async outcomes -------------------------------


class _CapturingSession:
    """Async-session stand-in. Subclasses override `execute` to return
    different fake rows for different SQL shapes."""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False
        self.rollback_called = False

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rollback_called = True

    async def refresh(self, _row):
        pass

    async def execute(self, _stmt, _params=None):
        raise NotImplementedError

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def delete(self, _row):
        pass


@pytest.mark.asyncio
async def test_process_async_dlqs_when_integration_disconnected(monkeypatch):
    integration = _make_integration(status=IntegrationStatus.disconnected)

    async def _load(*_a, **_k):
        return integration

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured.update(kwargs)
        captured["called"] = True
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "record_dlq", _record)

    # The function uses `async_session()` as a context manager — stub
    # it with a no-op.
    class _StubFactory:
        def __call__(self):
            return _CapturingSession()

    monkeypatch.setattr(tasks_module, "async_session", _StubFactory())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )
    assert result == {"status": "dlq", "reason": "disconnected"}
    assert captured["called"] is True
    assert "not connected" in captured["error_message"]


@pytest.mark.asyncio
async def test_process_async_dlqs_when_integration_missing(monkeypatch):
    async def _load(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured["error_message"] = kwargs.get("error_message")
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload={}
    )
    assert result["status"] == "dlq"
    assert result["reason"] == "integration_missing"
    assert "not found" in captured["error_message"]


@pytest.mark.asyncio
async def test_process_async_dlqs_on_missing_form_id(monkeypatch):
    integration = _make_integration()

    async def _load(*_a, **_k):
        return integration

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured["error_message"] = kwargs.get("error_message")
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    # Payload has no form_id.
    payload = {"lead_id": "L-1", "user_column_data": []}
    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=payload
    )
    assert result == {"status": "dlq", "reason": "missing_form_id"}
    assert "missing form_id" in captured["error_message"]


@pytest.mark.asyncio
async def test_process_async_dlqs_on_no_subscription(monkeypatch):
    integration = _make_integration()

    async def _load(*_a, **_k):
        return integration

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    async def _find_none(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "find_subscription", _find_none)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured["error_message"] = kwargs.get("error_message")
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )
    assert result == {"status": "dlq", "reason": "no_subscription"}
    assert "no enabled subscription" in captured["error_message"]


@pytest.mark.asyncio
async def test_process_async_dlqs_when_subscription_disabled(monkeypatch):
    integration = _make_integration()

    async def _load(*_a, **_k):
        return integration

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    sub = _make_subscription(enabled=False)

    async def _find(*_a, **_k):
        return sub

    monkeypatch.setattr(tasks_module, "find_subscription", _find)

    async def _record(*_a, **_k):
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )
    assert result["status"] == "dlq"
    assert result["reason"] == "no_subscription"


# --- 6. Happy path (full lead-creation pipeline) ------------------------


@pytest.mark.asyncio
async def test_process_async_creates_contact_and_lead(monkeypatch):
    integration = _make_integration()

    async def _load(*_a, **_k):
        return integration

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)

    sub = _make_subscription()

    async def _find_sub(*_a, **_k):
        return sub

    monkeypatch.setattr(tasks_module, "find_subscription", _find_sub)

    # No existing lead with this external_lead_id.
    async def _no_existing_lead(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _no_existing_lead)

    # No existing contact.
    async def _no_existing_contact(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "find_existing_contact", _no_existing_contact)

    new_contact_id = uuid.uuid4()
    new_lead_id = uuid.uuid4()

    async def _create_contact(*_a, **kwargs):
        return MagicMock(id=new_contact_id)

    captured: dict[str, Any] = {}

    async def _ingest_lead(*_a, **kwargs):
        # Step 6: channels now route through `ingest_lead` instead of
        # calling `create_lead` directly. Capture the payload it
        # would have built so we can still assert on attribution shape.
        captured["lead_payload"] = kwargs["lead_payload"]
        captured["source"] = kwargs["source"]
        captured["contact_id"] = kwargs["contact_id"]
        from src.app.core.leads.ingest import IngestResult

        return IngestResult(
            action="created",
            lead_id=new_lead_id,
            contact_id=new_contact_id,
            assignee_id=None,
        )

    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "ingest_lead", _ingest_lead)

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module.audit, "log", _noop_audit)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )

    assert result == {
        "status": "created",
        "lead_id": str(new_lead_id),
    }
    lead_payload = captured["lead_payload"]
    assert lead_payload.contact_id == new_contact_id
    assert lead_payload.source.value == "google_ads"
    # Attribution carries the spec'd ids.
    assert lead_payload.attribution["external_form_id"] == "form-1"
    assert lead_payload.attribution["external_lead_id"] == "lead-abc"
    assert lead_payload.attribution["campaign_id"] == "camp-1"
    assert lead_payload.attribution["gclid"] == "gclid-xyz"
    # ingest_lead received the right source + contact id.
    assert captured["source"].value == "google_ads"
    assert captured["contact_id"] == new_contact_id


@pytest.mark.asyncio
async def test_process_async_idempotency_skips_existing_lead(monkeypatch):
    """Replay of a payload we already processed must NOT double-create."""
    integration = _make_integration()
    sub = _make_subscription()

    async def _load(*_a, **_k):
        return integration

    async def _find_sub(*_a, **_k):
        return sub

    existing_lead_id = uuid.uuid4()

    async def _existing(*_a, **_k):
        return existing_lead_id

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)
    monkeypatch.setattr(tasks_module, "find_subscription", _find_sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _existing)

    create_contact_called = {"called": False}

    async def _create_contact(*_a, **_k):
        create_contact_called["called"] = True
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )
    assert result == {
        "status": "duplicate",
        "lead_id": str(existing_lead_id),
    }
    # Short-circuit: NO contact created, NO lead created.
    assert create_contact_called["called"] is False


@pytest.mark.asyncio
async def test_process_async_reuses_existing_contact_on_dedup(monkeypatch):
    integration = _make_integration()
    sub = _make_subscription()

    async def _load(*_a, **_k):
        return integration

    async def _find_sub(*_a, **_k):
        return sub

    async def _no_existing_lead(*_a, **_k):
        return None

    existing_contact_id = uuid.uuid4()

    async def _existing_contact(*_a, **_k):
        return existing_contact_id

    monkeypatch.setattr(tasks_module, "_load_integration_unscoped", _load)
    monkeypatch.setattr(tasks_module, "find_subscription", _find_sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _no_existing_lead)
    monkeypatch.setattr(tasks_module, "find_existing_contact", _existing_contact)

    contact_create_called = {"called": False}

    async def _create_contact(*_a, **_k):
        contact_create_called["called"] = True
        return MagicMock(id=uuid.uuid4())

    new_lead_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def _ingest_lead(*_a, **kwargs):
        captured["lead_payload"] = kwargs["lead_payload"]
        captured["contact_id"] = kwargs["contact_id"]
        from src.app.core.leads.ingest import IngestResult

        return IngestResult(
            action="created",
            lead_id=new_lead_id,
            contact_id=kwargs["contact_id"],
            assignee_id=None,
        )

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "ingest_lead", _ingest_lead)
    monkeypatch.setattr(tasks_module.audit, "log", _noop_audit)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_google_lead_async(
        integration_id=_INTEGRATION_ID, payload=_sample_payload()
    )
    assert result["status"] == "created"
    # Reused existing contact — no new contact created.
    assert contact_create_called["called"] is False
    # ingest_lead got the existing contact id.
    assert captured["contact_id"] == existing_contact_id
    assert captured["lead_payload"].contact_id == existing_contact_id


# --- 7. Service: webhook_secret lifecycle -------------------------------


class TestWebhookSecretLifecycle:
    def test_new_secret_is_url_safe_and_long(self):
        s = integration_service._new_webhook_secret()
        # url-safe-base64 of 32 random bytes = ~43 chars
        assert len(s) > 32
        # No padding, no slashes — safe to embed in URLs.
        assert "/" not in s
        assert "+" not in s
        assert "=" not in s

    def test_two_secrets_differ(self):
        a = integration_service._new_webhook_secret()
        b = integration_service._new_webhook_secret()
        assert a != b


# --- 8. DLQ replay ------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_dlq_calls_delay_and_marks_replayed(monkeypatch):
    actor_id = uuid.uuid4()
    dlq_row = IntegrationDLQ(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        provider=IntegrationProvider.google_ads,
        payload={"google_key": _SECRET, "form_id": "F-1", "lead_id": "L-1"},
        error_message="prior failure",
        retries_attempted=5,
    )

    async def _get_dlq(*_a, **_k):
        return dlq_row

    monkeypatch.setattr(dlq_module, "get_dlq", _get_dlq)

    captured: dict[str, Any] = {}

    class _FakeTask:
        def delay(self, *args, **_):
            captured["args"] = args

    monkeypatch.setattr(
        "src.app.core.integrations.google.tasks.process_google_lead",
        _FakeTask(),
    )

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(dlq_module.audit, "log", _noop_audit)

    session = _CapturingSession()
    result = await dlq_module.replay_dlq(session, dlq_id=dlq_row.id, actor_id=actor_id)

    assert result is dlq_row
    assert dlq_row.replayed_at is not None
    assert dlq_row.replayed_by == actor_id
    # The task was re-enqueued with the original payload.
    assert captured["args"][0] == str(_INTEGRATION_ID)
    assert captured["args"][1]["lead_id"] == "L-1"


@pytest.mark.asyncio
async def test_replay_dlq_409_when_integration_deleted(monkeypatch):
    dlq_row = IntegrationDLQ(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=None,  # integration was hard-deleted
        provider=IntegrationProvider.google_ads,
        payload={},
        error_message="x",
        retries_attempted=5,
    )

    async def _get_dlq(*_a, **_k):
        return dlq_row

    monkeypatch.setattr(dlq_module, "get_dlq", _get_dlq)

    session = _CapturingSession()
    with pytest.raises(Exception) as exc:
        await dlq_module.replay_dlq(session, dlq_id=dlq_row.id, actor_id=uuid.uuid4())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_replay_dlq_404_when_missing(monkeypatch):
    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(dlq_module, "get_dlq", _none)

    session = _CapturingSession()
    with pytest.raises(Exception) as exc:
        await dlq_module.replay_dlq(session, dlq_id=uuid.uuid4(), actor_id=uuid.uuid4())
    assert exc.value.status_code == 404
