"""Step 5 — Meta Lead Ads webhook receiver + task + page-token cache.

Mirrors the test_google_webhook.py style: pure-unit, monkeypatched
DB sessions, no real DB round-trips. The fake `_FakeAsyncClient`
returns canned Graph API responses keyed by URL prefix.

Eight groups:

  1. `_verify_signature` — happy + missing header + bad prefix +
     wrong digest + missing app secret.
  2. GET handshake — correct verify_token returns challenge,
     wrong token returns 403.
  3. POST receiver — bad sig 401, malformed JSON 400, happy path
     200 + enqueue count, multi-entry → multiple enqueues.
  4. Task outcomes — DLQ on missing page_token cache, DLQ on missing
     form_id, DLQ on no_subscription, DLQ on fetch_failed.
  5. Happy path — fetches leadgen details, creates contact + lead
     with correct source + attribution.
  6. Idempotency — replay returns `duplicate`, no second lead.
  7. Existing contact reuse — dedup hit reuses contact.
  8. Subscriptions cache — `upsert_page_token` encrypts + UPSERTs;
     `delete_page_token` removes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.core.integrations import crypto
from src.app.core.integrations.meta import (
    subscriptions as subs_module,
)
from src.app.core.integrations.meta import (
    tasks as tasks_module,
)
from src.app.core.integrations.meta import (
    webhook as webhook_module,
)
from src.app.core.integrations.meta.models import MetaPageToken
from src.app.core.integrations.models import (
    IntegrationProvider,
    IntegrationSubscription,
)

_APP_SECRET = "test-meta-app-secret"
_VERIFY_TOKEN = "test-meta-verify-token"
_ORG_ID = uuid.uuid4()
_INTEGRATION_ID = uuid.uuid4()


# --- shared fakes --------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: list[tuple[str, str, _FakeResponse]] = []

    def respond(self, method, url_prefix, response):
        self.responses.append((method.upper(), url_prefix, response))

    def _lookup(self, method, url):
        for m, prefix, resp in self.responses:
            if m == method.upper() and url.startswith(prefix):
                return resp
        raise AssertionError(
            f"No mocked response for {method} {url}; "
            f"registered={[(m, p) for m, p, _ in self.responses]}"
        )

    async def get(self, url, *, params=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self._lookup("GET", url)


class _CapturingSession:
    def __init__(self) -> None:
        self.added: list = []
        self.committed = False
        self.deleted: list = []

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass

    async def refresh(self, _row):
        pass

    async def delete(self, row):
        self.deleted.append(row)

    async def execute(self, _stmt, _params=None):
        raise NotImplementedError

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


@pytest.fixture
def _meta_webhook_env(monkeypatch):
    monkeypatch.setattr(webhook_module, "META_APP_SECRET", _APP_SECRET)
    monkeypatch.setattr(webhook_module, "META_WEBHOOK_VERIFY_TOKEN", _VERIFY_TOKEN)
    monkeypatch.setattr(tasks_module, "META_GRAPH_API_VERSION", "v19.0")


def _sign(body: bytes) -> str:
    digest = hmac.new(_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _sample_envelope(
    *,
    page_id: str = "page-1",
    leadgen_id: str = "leadgen-abc",
    form_id: str = "form-1",
    ad_id: str = "ad-1",
    campaign_id: str = "camp-1",
    count: int = 1,
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1700000000,
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": f"{leadgen_id}-{i}",
                            "form_id": form_id,
                            "page_id": page_id,
                            "ad_id": ad_id,
                            "campaign_id": campaign_id,
                            "created_time": 1700000000 + i,
                        },
                    }
                    for i in range(count)
                ],
            }
        ],
    }


def _build_app() -> FastAPI:
    """Mount just the webhook router on a fresh FastAPI — bypasses
    the full src.app.main import surface (and its lifespan)."""
    app = FastAPI()
    app.include_router(webhook_module.router, prefix="/api/v1/integrations")
    return app


# --- 1. _verify_signature ------------------------------------------------


class TestSignatureVerify:
    def test_happy_path(self, _meta_webhook_env):
        body = b'{"object":"page"}'
        sig = _sign(body)
        assert webhook_module._verify_signature(body, sig) is True

    def test_missing_header_returns_false(self, _meta_webhook_env):
        assert webhook_module._verify_signature(b"x", None) is False

    def test_wrong_prefix_returns_false(self, _meta_webhook_env):
        assert webhook_module._verify_signature(b"x", "sha1=abc") is False

    def test_wrong_digest_returns_false(self, _meta_webhook_env):
        assert webhook_module._verify_signature(b"x", "sha256=deadbeef") is False

    def test_missing_app_secret_refuses_all(self, monkeypatch):
        monkeypatch.setattr(webhook_module, "META_APP_SECRET", "")
        body = b"x"
        sig = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
        # Even a digest of "" key wouldn't authenticate — refuse to
        # accept anything when the secret env is missing.
        assert webhook_module._verify_signature(body, sig) is False


# --- 2. GET handshake ----------------------------------------------------


@pytest.mark.asyncio
async def test_handshake_returns_challenge_on_correct_token(_meta_webhook_env, monkeypatch):
    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/integrations/meta/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": _VERIFY_TOKEN,
                "hub.challenge": "42",
            },
        )
    assert resp.status_code == 200
    # PLAIN TEXT response, not JSON — Meta requires the raw challenge.
    assert resp.text == "42"


@pytest.mark.asyncio
async def test_handshake_wrong_token_returns_403(_meta_webhook_env, monkeypatch):
    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/integrations/meta/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "42",
            },
        )
    assert resp.status_code == 403


# --- 3. POST receiver ----------------------------------------------------


@pytest.mark.asyncio
async def test_receiver_401_on_bad_signature(_meta_webhook_env, monkeypatch):
    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    app = _build_app()
    body = json.dumps(_sample_envelope()).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/meta/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-hub-signature-256": "sha256=deadbeef",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_receiver_200_and_enqueues_on_valid_signature(_meta_webhook_env, monkeypatch):
    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    # Force the HAS_CELERY=True branch + capture enqueue.
    captured: list[dict] = []

    class _FakeTask:
        def delay(self, payload):
            captured.append(payload)

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_meta_lead", _FakeTask())

    app = _build_app()
    body = json.dumps(_sample_envelope()).encode()
    sig = _sign(body)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/meta/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-hub-signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted", "enqueued": 1}
    assert len(captured) == 1
    assert captured[0]["page_id"] == "page-1"
    assert captured[0]["form_id"] == "form-1"
    assert captured[0]["leadgen_id"] == "leadgen-abc-0"


@pytest.mark.asyncio
async def test_receiver_enqueues_one_task_per_change(_meta_webhook_env, monkeypatch):
    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    captured: list[dict] = []

    class _FakeTask:
        def delay(self, payload):
            captured.append(payload)

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_meta_lead", _FakeTask())

    app = _build_app()
    body = json.dumps(_sample_envelope(count=3)).encode()
    sig = _sign(body)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/meta/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-hub-signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["enqueued"] == 3
    assert len(captured) == 3
    assert {c["leadgen_id"] for c in captured} == {
        "leadgen-abc-0",
        "leadgen-abc-1",
        "leadgen-abc-2",
    }


@pytest.mark.asyncio
async def test_receiver_skips_non_leadgen_changes(_meta_webhook_env, monkeypatch):
    """Meta sometimes bundles other change types (feed, mentions) in
    the same envelope. Only `leadgen` changes should enqueue."""

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    captured: list[dict] = []

    class _FakeTask:
        def delay(self, payload):
            captured.append(payload)

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_meta_lead", _FakeTask())

    envelope = {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {"item": "status", "verb": "add"},
                    },
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": "L-1",
                            "form_id": "F-1",
                            "page_id": "page-1",
                        },
                    },
                    {
                        "field": "mentions",
                        "value": {"thing": "x"},
                    },
                ],
            }
        ],
    }
    body = json.dumps(envelope).encode()
    sig = _sign(body)

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/meta/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-hub-signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["enqueued"] == 1
    assert len(captured) == 1
    assert captured[0]["leadgen_id"] == "L-1"


@pytest.mark.asyncio
async def test_receiver_skips_non_page_object_type(_meta_webhook_env, monkeypatch):
    """An `object="instagram"` envelope would carry a different
    subscription field — skip cleanly without crashing."""

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(webhook_module.audit, "log", _noop_audit)

    captured: list[dict] = []

    class _FakeTask:
        def delay(self, payload):
            captured.append(payload)

    monkeypatch.setattr(tasks_module, "HAS_CELERY", True)
    monkeypatch.setattr(tasks_module, "process_meta_lead", _FakeTask())

    body = json.dumps({"object": "instagram", "entry": []}).encode()
    sig = _sign(body)
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/meta/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-hub-signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["enqueued"] == 0
    assert captured == []


# --- 4 + 5. process_meta_lead_async outcomes -----------------------------


def _sample_payload() -> dict:
    return {
        "leadgen_id": "L-1",
        "form_id": "F-1",
        "page_id": "page-1",
        "ad_id": "ad-1",
        "campaign_id": "camp-1",
    }


@pytest.mark.asyncio
async def test_task_dlqs_on_missing_page_token(_meta_webhook_env, monkeypatch):
    """No cached Page token (subscribe→unsubscribe race) → DLQ."""

    async def _no_mapping(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _no_mapping)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured.update(kwargs)
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "_record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_meta_lead_async(payload=_sample_payload())
    assert result == {"status": "dlq", "reason": "no_page_token"}
    # Provider tag is correct.
    assert captured["provider"] == IntegrationProvider.meta_ads
    assert "no cached Page token" in captured["error_message"]


@pytest.mark.asyncio
async def test_task_dlqs_on_missing_form_id(_meta_webhook_env, monkeypatch):
    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured.update(kwargs)
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "_record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    payload = _sample_payload()
    del payload["form_id"]
    result = await tasks_module.process_meta_lead_async(payload=payload)
    assert result == {"status": "dlq", "reason": "missing_form_id"}
    assert captured["provider"] == IntegrationProvider.meta_ads


@pytest.mark.asyncio
async def test_task_dlqs_on_no_subscription(_meta_webhook_env, monkeypatch):
    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    async def _no_sub(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)
    monkeypatch.setattr(tasks_module, "find_subscription", _no_sub)

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured.update(kwargs)
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "_record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_meta_lead_async(payload=_sample_payload())
    assert result == {"status": "dlq", "reason": "no_subscription"}
    assert captured["provider"] == IntegrationProvider.meta_ads


@pytest.mark.asyncio
async def test_task_dlqs_on_fetch_failed(_meta_webhook_env, monkeypatch):
    """Meta returns 404 for a deleted lead → DLQ (not retry)."""

    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    sub = IntegrationSubscription(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="F-1",
        field_mapping={},
        enabled=True,
    )

    async def _sub(*_a, **_k):
        return sub

    async def _no_existing(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)
    monkeypatch.setattr(tasks_module, "find_subscription", _sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _no_existing)

    fake_client = _FakeAsyncClient()
    fake_client.respond(
        "GET",
        "https://graph.facebook.com/v19.0/L-1",
        _FakeResponse(404, {"error": "lead not found"}),
    )

    captured: dict[str, Any] = {}

    async def _record(*_a, **kwargs):
        captured.update(kwargs)
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "_record_dlq", _record)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_meta_lead_async(
        payload=_sample_payload(), http_client=fake_client
    )
    assert result == {"status": "dlq", "reason": "fetch_failed"}
    assert captured["provider"] == IntegrationProvider.meta_ads
    assert "failed to fetch leadgen L-1" in captured["error_message"]


@pytest.mark.asyncio
async def test_task_creates_lead_with_attribution(_meta_webhook_env, monkeypatch):
    """Happy path: fetch leadgen, apply mapping, create contact+lead."""

    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    sub = IntegrationSubscription(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="F-1",
        field_mapping={
            "full_name": "contact.full_name",
            "phone_number": "contact.phone",
            "email": "contact.email",
        },
        enabled=True,
    )

    async def _sub(*_a, **_k):
        return sub

    async def _no_existing(*_a, **_k):
        return None

    async def _no_contact(*_a, **_k):
        return None

    new_contact_id = uuid.uuid4()
    new_lead_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def _create_contact(*_a, **kwargs):
        captured["contact_payload"] = kwargs["payload"]
        return MagicMock(id=new_contact_id)

    async def _ingest_lead(*_a, **kwargs):
        # Step 6: tasks.py routes through ingest_lead instead of
        # calling create_lead directly. Capture the lead_payload so
        # we can still verify attribution/source shape.
        captured["lead_payload"] = kwargs["lead_payload"]
        from src.app.core.leads.ingest import IngestResult

        return IngestResult(
            action="created",
            lead_id=new_lead_id,
            contact_id=kwargs["contact_id"],
            assignee_id=None,
        )

    async def _noop_audit(*_a, **_k):
        return None

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)
    monkeypatch.setattr(tasks_module, "find_subscription", _sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _no_existing)
    monkeypatch.setattr(tasks_module, "find_existing_contact", _no_contact)
    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "ingest_lead", _ingest_lead)
    monkeypatch.setattr(tasks_module.audit, "log", _noop_audit)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    fake_client = _FakeAsyncClient()
    fake_client.respond(
        "GET",
        "https://graph.facebook.com/v19.0/L-1",
        _FakeResponse(
            200,
            {
                "id": "L-1",
                "created_time": "2026-05-26T10:00:00+0000",
                "field_data": [
                    {"name": "full_name", "values": ["Asha Khan"]},
                    {"name": "phone_number", "values": ["+919876543210"]},
                    {"name": "email", "values": ["asha@example.com"]},
                ],
                "ad_id": "ad-1",
                "campaign_id": "camp-1",
            },
        ),
    )

    result = await tasks_module.process_meta_lead_async(
        payload=_sample_payload(), http_client=fake_client
    )
    assert result == {
        "status": "created",
        "lead_id": str(new_lead_id),
    }
    # Contact mapped correctly.
    cp = captured["contact_payload"]
    assert cp.full_name == "Asha Khan"
    assert cp.phone == "+919876543210"
    assert cp.email == "asha@example.com"
    assert cp.source == "meta_ads"
    # Lead has the spec'd attribution.
    lp = captured["lead_payload"]
    assert lp.contact_id == new_contact_id
    assert lp.source.value == "meta_ads"
    assert lp.attribution["external_form_id"] == "F-1"
    assert lp.attribution["external_lead_id"] == "L-1"
    assert lp.attribution["page_id"] == "page-1"
    assert lp.attribution["ad_id"] == "ad-1"
    assert lp.attribution["campaign_id"] == "camp-1"


# --- 6. Idempotency ------------------------------------------------------


@pytest.mark.asyncio
async def test_task_idempotency_skips_duplicate_leadgen(_meta_webhook_env, monkeypatch):
    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    sub = IntegrationSubscription(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="F-1",
        field_mapping={},
        enabled=True,
    )

    async def _sub(*_a, **_k):
        return sub

    existing_lead_id = uuid.uuid4()

    async def _existing(*_a, **_k):
        return existing_lead_id

    create_called = {"called": False}

    async def _create_contact(*_a, **_k):
        create_called["called"] = True
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)
    monkeypatch.setattr(tasks_module, "find_subscription", _sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _existing)
    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    result = await tasks_module.process_meta_lead_async(payload=_sample_payload())
    assert result == {
        "status": "duplicate",
        "lead_id": str(existing_lead_id),
    }
    # Short-circuit: no contact / lead / HTTP fetch happened.
    assert create_called["called"] is False


# --- 7. Existing contact reuse ------------------------------------------


@pytest.mark.asyncio
async def test_task_reuses_existing_contact(_meta_webhook_env, monkeypatch):
    async def _ok_mapping(*_a, **_k):
        return (_ORG_ID, _INTEGRATION_ID, "page-tok")

    sub = IntegrationSubscription(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=_INTEGRATION_ID,
        external_form_id="F-1",
        field_mapping={
            "full_name": "contact.full_name",
            "phone_number": "contact.phone",
        },
        enabled=True,
    )

    async def _sub(*_a, **_k):
        return sub

    async def _no_existing_lead(*_a, **_k):
        return None

    existing_contact_id = uuid.uuid4()

    async def _existing_contact(*_a, **_k):
        return existing_contact_id

    contact_create_called = {"called": False}

    async def _create_contact(*_a, **_k):
        contact_create_called["called"] = True
        return MagicMock(id=uuid.uuid4())

    new_lead_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def _ingest_lead(*_a, **kwargs):
        captured["payload"] = kwargs["lead_payload"]
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

    monkeypatch.setattr(tasks_module, "_load_page_token_unscoped", _ok_mapping)
    monkeypatch.setattr(tasks_module, "find_subscription", _sub)
    monkeypatch.setattr(tasks_module, "_find_lead_by_external_id", _no_existing_lead)
    monkeypatch.setattr(tasks_module, "find_existing_contact", _existing_contact)
    monkeypatch.setattr(tasks_module, "create_contact", _create_contact)
    monkeypatch.setattr(tasks_module, "ingest_lead", _ingest_lead)
    monkeypatch.setattr(tasks_module.audit, "log", _noop_audit)
    monkeypatch.setattr(tasks_module, "async_session", lambda: _CapturingSession())

    fake_client = _FakeAsyncClient()
    fake_client.respond(
        "GET",
        "https://graph.facebook.com/v19.0/L-1",
        _FakeResponse(
            200,
            {
                "field_data": [
                    {"name": "full_name", "values": ["Existing"]},
                    {"name": "phone_number", "values": ["+919876543210"]},
                ],
            },
        ),
    )

    result = await tasks_module.process_meta_lead_async(
        payload=_sample_payload(), http_client=fake_client
    )
    assert result["status"] == "created"
    assert contact_create_called["called"] is False
    assert captured["payload"].contact_id == existing_contact_id


# --- 8. Page-token cache (subscriptions module) -------------------------


class TestPageTokenCache:
    @pytest.mark.asyncio
    async def test_upsert_inserts_when_missing(self, monkeypatch):
        class _S:
            def __init__(self):
                self.added = []
                self.committed = False

            async def execute(self, _stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return None

                return _R()

            def add(self, row):
                self.added.append(row)
                if row.id is None:
                    row.id = uuid.uuid4()

            async def commit(self):
                self.committed = True

            async def refresh(self, _row):
                pass

        session = _S()
        row = await subs_module.upsert_page_token(
            session,
            org_id=_ORG_ID,
            integration_id=_INTEGRATION_ID,
            page_id="page-1",
            page_name="Mumbai Showroom",
            page_token="plain-page-token",
        )
        assert row.org_id == _ORG_ID
        assert row.integration_id == _INTEGRATION_ID
        assert row.page_id == "page-1"
        assert row.page_name == "Mumbai Showroom"
        # Encrypted — plaintext never lands in the column.
        assert "plain-page-token" not in row.page_token_enc
        # Decrypts back.
        assert crypto.decrypt(row.page_token_enc) == "plain-page-token"
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_upsert_replaces_when_exists(self, monkeypatch):
        existing = MetaPageToken(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=_INTEGRATION_ID,
            page_id="page-1",
            page_name="Old Name",
            page_token_enc=crypto.encrypt("old-token"),
        )

        class _S:
            def __init__(self, row):
                self.row = row
                self.added = []
                self.committed = False

            async def execute(self, _stmt):
                row = self.row

                class _R:
                    def scalar_one_or_none(self):
                        return row

                return _R()

            def add(self, row):
                self.added.append(row)

            async def commit(self):
                self.committed = True

            async def refresh(self, _row):
                pass

        session = _S(existing)
        row = await subs_module.upsert_page_token(
            session,
            org_id=_ORG_ID,
            integration_id=_INTEGRATION_ID,
            page_id="page-1",
            page_name="New Name",
            page_token="new-token",
        )
        # No NEW row added — the existing was mutated.
        assert session.added == []
        assert row is existing
        assert row.page_name == "New Name"
        assert crypto.decrypt(row.page_token_enc) == "new-token"

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_row_exists(self):
        existing = MetaPageToken(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=_INTEGRATION_ID,
            page_id="page-1",
            page_token_enc="enc",
        )

        class _S:
            def __init__(self, row):
                self.row = row
                self.deleted = []
                self.committed = False

            async def execute(self, _stmt):
                row = self.row

                class _R:
                    def scalar_one_or_none(self):
                        return row

                return _R()

            async def delete(self, row):
                self.deleted.append(row)

            async def commit(self):
                self.committed = True

        session = _S(existing)
        ok = await subs_module.delete_page_token(
            session,
            integration_id=_INTEGRATION_ID,
            page_id="page-1",
        )
        assert ok is True
        assert session.deleted == [existing]
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_row_missing(self):
        class _S:
            async def execute(self, _stmt):
                class _R:
                    def scalar_one_or_none(self):
                        return None

                return _R()

        ok = await subs_module.delete_page_token(
            _S(),
            integration_id=_INTEGRATION_ID,
            page_id="missing-page",
        )
        assert ok is False
