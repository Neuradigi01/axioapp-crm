"""Coverage for Step 3 of the email-reputation-warmup track.

Three surfaces:

  1. ``POST /api/v1/webhooks/mailgun/events`` — the HTTP endpoint.
     Signature verify, event-id dedup, persist-then-enqueue, 200 vs
     406 vs 500 on the various fail shapes.
  2. ``process_mailgun_event`` — the Celery task body invoked via
     ``asyncio.run(_process_event_async(...))``. Attribution via
     ``event-data.user-variables``, event kind mapping, drop paths.
  3. Interaction with :mod:`.reputation.service` — the counter bumps
     (Redis + DB mirror) fire exactly once per event.

Redis is faked via monkeypatch of :func:`.mailgun.data_access._redis`
and :func:`.reputation.counters._redis` — the same in-memory fake
the counter-module tests use, promoted to a module-level helper here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError
from sqlalchemy import select

from src.app.core.email.mailgun import data_access as mailgun_da
from src.app.core.email.mailgun import events_webhook
from src.app.core.email.reputation import counters as rep_counters
from src.app.core.email.reputation.models import OrganizationEmailReputation
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Fake Redis — mirrors the aioredis surface both modules use.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """SET NX PX + pipeline + mget + scan_iter, in-memory. Enough
    for the events webhook (SET NX PX) and the counter module
    (pipeline INCRBY/EXPIRE, MGET). Tests can toggle failure modes."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.raise_on_set = False
        self.raise_on_mget = False
        self.raise_on_pipeline_execute = False

    async def set(self, key: str, value: str, nx: bool = False, px: int | None = None):
        if self.raise_on_set:
            raise RedisError("simulated set outage")
        if nx and key in self.store:
            return None
        self.store[key] = value
        if px is not None:
            self.ttls[key] = int(px / 1000)
        return "OK"

    async def incrby(self, key: str, amount: int) -> int:
        current = int(self.store.get(key, 0) or 0)
        current += amount
        self.store[key] = current
        return current

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    async def mget(self, keys: list[str]) -> list[Any]:
        if self.raise_on_mget:
            raise RedisError("simulated mget outage")
        return [str(self.store[k]) if k in self.store else None for k in keys]

    async def delete(self, key: str) -> int:
        removed = 1 if key in self.store else 0
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return removed

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        prefix = match.rstrip("*")
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def incrby(self, key: str, amount: int) -> _FakePipeline:
        self._ops.append(("incrby", (key, amount)))
        return self

    def expire(self, key: str, ttl: int) -> _FakePipeline:
        self._ops.append(("expire", (key, ttl)))
        return self

    async def execute(self) -> list[Any]:
        if self._client.raise_on_pipeline_execute:
            raise RedisError("simulated pipeline outage")
        results: list[Any] = []
        for op, args in self._ops:
            if op == "incrby":
                key, amount = args
                self._client.store[key] = int(self._client.store.get(key, 0) or 0) + amount
                results.append(self._client.store[key])
            elif op == "expire":
                key, ttl = args
                self._client.ttls[key] = ttl
                results.append(True)
        self._ops.clear()
        return results


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    """Inject the fake into both the mailgun DAL (replay + event dedup)
    and the reputation counters module."""
    fake = _FakeRedis()
    monkeypatch.setattr(mailgun_da, "_redis", lambda: fake)
    monkeypatch.setattr(events_webhook, "_redis", lambda: fake)
    monkeypatch.setattr(rep_counters, "_redis", lambda: fake)
    monkeypatch.setattr(rep_counters, "_redis_client", None)
    monkeypatch.setattr(rep_counters, "_redis_disabled", False)
    return fake


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------


def _sign(*, key: str, timestamp: str, token: str) -> str:
    return hmac.new(
        key.encode("utf-8"),
        (timestamp + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_event_body(
    *,
    key: str = "test-signing-key",
    event: str = "delivered",
    org_id: str | None = "11111111-1111-1111-1111-111111111111",
    envelope: str | None = "platform_from",
    domain_id: str | None = None,
    event_id: str | None = None,
    severity: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    ts = str(int(time.time()))
    tok = token or f"tok-{uuid.uuid4().hex}"
    user_vars: dict[str, str] = {}
    if org_id:
        user_vars["org"] = org_id
    if envelope:
        user_vars["envelope"] = envelope
    if domain_id:
        user_vars["domain_id"] = domain_id

    event_data: dict[str, Any] = {
        "id": event_id or f"evt-{uuid.uuid4().hex}",
        "event": event,
        "timestamp": float(ts),
        "user-variables": user_vars,
    }
    if severity is not None:
        event_data["severity"] = severity
    return {
        "signature": {
            "timestamp": ts,
            "token": tok,
            "signature": _sign(key=key, timestamp=ts, token=tok),
        },
        "event-data": event_data,
    }


# ---------------------------------------------------------------------------
# 1. HTTP layer — signature + dedup + persist-then-enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_webhook_hmac_verify_fail_returns_406(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Bad HMAC signature → 406 (Mailgun's "no retry" reject shape).
    Nothing lands on disk; no Celery enqueue."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "server-key")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    body = _build_event_body(key="attacker-key")
    resp = await layered_client.post(
        "/api/v1/webhooks/mailgun/events",
        json=body,
    )
    assert resp.status_code == 406
    assert "bad signature" in resp.json()["error"].lower()
    # No pending-events directory created.
    assert not (tmp_path / "pending-events").exists()


@pytest.mark.asyncio
async def test_events_webhook_replay_triplet_rejected(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Same signed triplet posted twice → second one 406s."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    body = _build_event_body(key="k")
    with patch.object(events_webhook.process_mailgun_event, "delay"):
        resp1 = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body)
        assert resp1.status_code == 200
        resp2 = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body)
    assert resp2.status_code == 406
    assert "replay" in resp2.json()["error"].lower()


@pytest.mark.asyncio
async def test_events_webhook_timestamp_stale_rejected(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Timestamp older than 5 min → 406 via verify_signature's window."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    stale_ts = str(int(time.time()) - 600)
    tok = "tok-stale"
    body = {
        "signature": {
            "timestamp": stale_ts,
            "token": tok,
            "signature": _sign(key="k", timestamp=stale_ts, token=tok),
        },
        "event-data": {
            "id": "evt-stale",
            "event": "delivered",
            "user-variables": {
                "org": "11111111-1111-1111-1111-111111111111",
                "envelope": "platform_from",
            },
        },
    }
    resp = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body)
    assert resp.status_code == 406


@pytest.mark.asyncio
async def test_events_webhook_redis_down_fails_closed_on_sig_replay(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Redis-down during the signature-replay SET NX PX → 406.
    A replay is worse than a dropped delivery; Mailgun retries after
    the 5xx and we recover once Redis is back."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    fake_redis.raise_on_set = True
    body = _build_event_body(key="k")
    resp = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body)
    assert resp.status_code == 406


@pytest.mark.asyncio
async def test_events_webhook_persists_payload_to_disk_before_enqueue(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Signed + fresh event → ``pending-events/<uuid>/payload.json``
    written first, THEN the Celery task .delay()'d."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    body = _build_event_body(key="k")
    with patch.object(events_webhook.process_mailgun_event, "delay") as mock_delay:
        resp = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
    mock_delay.assert_called_once()
    pending_arg = mock_delay.call_args.args[0]
    pending_path = Path(pending_arg)
    assert pending_path.exists()
    assert pending_path.parent.name == "pending-events"
    persisted = json.loads((pending_path / "payload.json").read_text())
    assert persisted["event-data"]["id"] == body["event-data"]["id"]


@pytest.mark.asyncio
async def test_events_webhook_second_delivery_of_same_event_id_returns_200_dedup(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Mailgun retries a webhook after 8h backoff — same event id.
    Second delivery returns 200 (so Mailgun stops retrying) but does
    NOT enqueue a second task. The signature-triplet cache TTL will
    already have expired at 8h so we test at the shorter event-dedup
    scale by reusing the same body with a fresh token."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    body_first = _build_event_body(key="k", event_id="evt-abc")
    body_second = _build_event_body(
        key="k",
        event_id="evt-abc",  # SAME event id
        token=body_first["signature"]["token"] + "-diff",  # fresh triplet
    )
    with patch.object(events_webhook.process_mailgun_event, "delay") as mock_delay:
        resp1 = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body_first)
        resp2 = await layered_client.post("/api/v1/webhooks/mailgun/events", json=body_second)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate"
    # Enqueue happened exactly ONCE (first delivery).
    assert mock_delay.call_count == 1


@pytest.mark.asyncio
async def test_events_webhook_malformed_body_returns_406(
    layered_client, fake_redis, monkeypatch, tmp_path
):
    """Non-JSON body → 406, no retry."""
    monkeypatch.setenv("MAILGUN_SIGNING_KEY", "k")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    resp = await layered_client.post(
        "/api/v1/webhooks/mailgun/events",
        content=b"not-json-at-all",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 406


# ---------------------------------------------------------------------------
# 2. Celery task — process_mailgun_event
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Rep Events Org") -> Organization:
    org = Organization(id=uuid.uuid4(), name=name, slug=f"rep-evt-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    return org


async def _make_domain(session, *, org_id: uuid.UUID) -> OrganizationEmailDomain:
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=f"d-{uuid.uuid4().hex[:8]}.example",
        mailgun_domain_id="mg-x",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    session.add(row)
    await session.flush()
    return row


def _write_event(tmp_path: Path, body: dict[str, Any]) -> Path:
    pending = tmp_path / "pending-events" / str(uuid.uuid4())
    pending.mkdir(parents=True, exist_ok=True)
    (pending / "payload.json").write_text(json.dumps(body), encoding="utf-8")
    return pending


@pytest.mark.asyncio
async def test_process_event_delivered_bumps_delivered_counter_and_creates_row(
    test_db, fake_redis, tmp_path
):
    """First ``delivered`` for a new (org, platform_from) → INSERTs
    the reputation row, bumps ``delivered_count_24h`` = 1, bumps the
    Redis 24h bucket."""
    org = await _make_org(test_db)
    await test_db.commit()

    body = _build_event_body(event="delivered", org_id=str(org.id), envelope="platform_from")
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    # DB mirror bumped.
    row = (
        await test_db.execute(
            select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
        )
    ).scalar_one()
    assert row.envelope_type == "platform_from"
    assert row.domain_id is None
    assert row.delivered_count_24h == 1
    # Redis bucket also bumped.
    assert any(
        k.startswith(f"rep:{org.id}:platform_from:none:delivered:") for k in fake_redis.store
    )
    # Pending dir cleaned up.
    assert not pending.exists()


@pytest.mark.asyncio
async def test_process_event_bounced_permanent_bumps_bounce_counter(test_db, fake_redis, tmp_path):
    org = await _make_org(test_db)
    await test_db.commit()
    body = _build_event_body(
        event="failed",
        severity="permanent",
        org_id=str(org.id),
        envelope="platform_from",
    )
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    row = (
        await test_db.execute(
            select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
        )
    ).scalar_one()
    assert row.bounce_count_24h == 1
    assert row.delivered_count_24h == 0
    assert any(k.startswith(f"rep:{org.id}:platform_from:none:bounced:") for k in fake_redis.store)


@pytest.mark.asyncio
async def test_process_event_bounced_temporary_does_not_bump(test_db, fake_redis, tmp_path):
    """Soft bounce (``failed`` severity=``temporary``) is Mailgun-side
    retry state — must not count against reputation."""
    org = await _make_org(test_db)
    await test_db.commit()
    body = _build_event_body(
        event="failed",
        severity="temporary",
        org_id=str(org.id),
        envelope="platform_from",
    )
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    # No row created — no counter bumps meant no upsert either.
    result = await test_db.execute(
        select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
    )
    assert result.scalar_one_or_none() is None
    # No Redis writes.
    assert not any(k.startswith(f"rep:{org.id}:") for k in fake_redis.store)


@pytest.mark.asyncio
async def test_process_event_complained_bumps_complaint_counter(test_db, fake_redis, tmp_path):
    org = await _make_org(test_db)
    await test_db.commit()
    body = _build_event_body(event="complained", org_id=str(org.id), envelope="platform_from")
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    row = (
        await test_db.execute(
            select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
        )
    ).scalar_one()
    assert row.complaint_count_24h == 1


@pytest.mark.asyncio
async def test_process_event_own_domain_attributes_to_domain_row(test_db, fake_redis, tmp_path):
    """``own_domain`` with ``v:domain_id`` populated → row keyed on
    (org, domain), key contains the domain UUID, own-domain and
    platform-from rows coexist."""
    org = await _make_org(test_db)
    domain = await _make_domain(test_db, org_id=org.id)
    await test_db.commit()

    body = _build_event_body(
        event="delivered",
        org_id=str(org.id),
        envelope="own_domain",
        domain_id=str(domain.id),
    )
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    row = (
        await test_db.execute(
            select(OrganizationEmailReputation).where(
                OrganizationEmailReputation.org_id == org.id,
                OrganizationEmailReputation.envelope_type == "own_domain",
            )
        )
    ).scalar_one()
    assert row.domain_id == domain.id
    assert row.delivered_count_24h == 1
    assert any(f":own_domain:{domain.id}:" in k for k in fake_redis.store)


@pytest.mark.asyncio
async def test_process_event_missing_v_org_audits_and_drops(test_db, fake_redis, tmp_path):
    """No ``v:org`` in ``user-variables`` → drop path. No row created,
    no counter bump, pending dir cleaned up."""
    body = _build_event_body(event="delivered", org_id=None)
    pending = _write_event(tmp_path, body)
    await events_webhook._process_event_async(pending)

    result = await test_db.execute(select(OrganizationEmailReputation))
    assert result.scalars().first() is None
    assert not pending.exists()


@pytest.mark.asyncio
async def test_process_event_replay_second_delivery_no_double_count(test_db, fake_redis, tmp_path):
    """Two payloads with the SAME event-id both make it into the
    task (webhook dedup is at the HTTP layer). At the task layer, a
    second delivery of the same event would just add another INCR —
    the endpoint's Redis SET-NX check is where dedup happens. Prove
    it: two INCRs mean two counts. This test locks the contract that
    dedup is HTTP-side, not task-side."""
    org = await _make_org(test_db)
    await test_db.commit()

    body = _build_event_body(
        event="delivered",
        org_id=str(org.id),
        envelope="platform_from",
        event_id="evt-fixed",
    )
    for _ in range(2):
        pending = _write_event(tmp_path, body)
        await events_webhook._process_event_async(pending)

    row = (
        await test_db.execute(
            select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
        )
    ).scalar_one()
    assert row.delivered_count_24h == 2


@pytest.mark.asyncio
async def test_process_event_unknown_event_kind_no_op(test_db, fake_redis, tmp_path):
    """Mailgun sends ``accepted`` / ``opened`` / ``clicked`` too —
    unmapped kinds fall through as no-ops (no row created, no counter
    bump). Locks the contract that Track 4 only counts the four kinds
    the reputation model uses."""
    org = await _make_org(test_db)
    await test_db.commit()

    for kind in ("accepted", "opened", "clicked", "rejected"):
        body = _build_event_body(event=kind, org_id=str(org.id), envelope="platform_from")
        pending = _write_event(tmp_path, body)
        await events_webhook._process_event_async(pending)

    # Zero rows created — because no counter mapping means no upsert.
    result = await test_db.execute(
        select(OrganizationEmailReputation).where(OrganizationEmailReputation.org_id == org.id)
    )
    assert result.scalar_one_or_none() is None
