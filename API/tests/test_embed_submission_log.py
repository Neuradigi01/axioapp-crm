"""Step 9 — submission-log unit tests.

Two groups:

  1. Pure helpers (`hash_ip`).
  2. `submissions.submit` integration — same monkeypatch harness as
     Step 8, extended to assert that `log_service.record` is called
     with the right outcome + reason + payload-derived fields on
     each gate path (accepted / honeypot / min-time / rate-limited
     / invalid-payload / invalid-key=no-log).

We deliberately do NOT round-trip rows through the real DB here:
the project's `seeded_admin` / `layered_client` HTTP fixtures are
broken on this branch, and the prod-style `async_session()` engine
isn't safe to drive from pytest-asyncio inside a fixture (asyncpg's
"another operation in progress" error). Instead:

  - RLS for `embed_submissions` is enforced by `apply_rls(...)` in
    migration 0047; verified by inspection of the policy.
  - The `record` / `list_rows` / `summary` / `purge` round-trip is
    exercised by manual smoke (submit a lead in the dev environment;
    open Settings → Embed → Submission log; confirm the row appears).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.app.core.embed import log_service, submissions
from src.app.core.embed.models import EmbedSubmissionOutcome
from src.app.core.embed.rate_limit import RateLimitResult
from src.app.core.embed.schemas import (
    EmbedSubmission,
    SubmissionAttribution,
    WidgetConfigDocument,
    WidgetConfigField,
    WidgetConfigSpamProtection,
)


# --- 1. hash_ip pure function ---------------------------------------------


class TestHashIp:
    def test_known_ip_yields_16_hex_chars(self):
        out = log_service.hash_ip("203.0.113.42")
        assert out is not None
        assert len(out) == 16
        assert all(c in "0123456789abcdef" for c in out)

    def test_same_ip_same_hash(self):
        a = log_service.hash_ip("203.0.113.42")
        b = log_service.hash_ip("203.0.113.42")
        assert a == b

    def test_different_ips_different_hashes(self):
        a = log_service.hash_ip("203.0.113.42")
        b = log_service.hash_ip("203.0.113.43")
        assert a != b

    def test_none_and_unknown_return_none(self):
        assert log_service.hash_ip(None) is None
        assert log_service.hash_ip("") is None
        assert log_service.hash_ip("unknown") is None


# --- 2. submissions.submit integration — log rows on each gate path -------


_KEY_ID = uuid.uuid4()
_LEAD_ID = uuid.uuid4()
_CONTACT_ID = uuid.uuid4()


def _payload(**overrides) -> EmbedSubmission:
    base = dict(
        full_name="Asha Reddy",
        phone="+91 9000000000",
        attribution=SubmissionAttribution(
            referrer="https://customer.example/contact",
            landing_url="https://customer.example/contact?ref=ads",
        ),
    )
    base.update(overrides)
    return EmbedSubmission(**base)


def _config_row(*, spam=None):
    spam = spam or WidgetConfigSpamProtection()
    doc = WidgetConfigDocument(
        fields=[
            WidgetConfigField(
                key="full_name", label="Name", required=True, order=0,
                field_type="text",
            ),
            WidgetConfigField(
                key="phone", label="Phone", required=True, order=1,
                field_type="tel",
            ),
        ],
        spam_protection=spam,
    )
    return SimpleNamespace(config=doc.model_dump(mode="json"))


@dataclass
class _LogCapture:
    """Captures the record() calls so tests can assert without
    touching the database."""

    calls: list[dict]

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)


class _SubmitHarness:
    def __init__(self, monkeypatch, *, org_id: uuid.UUID, spam=None):
        self.monkeypatch = monkeypatch
        self.org_id = org_id
        self.log_capture = _LogCapture(calls=[])

        async def _find_key(plain, ip=None):
            return SimpleNamespace(
                id=_KEY_ID, org_id=org_id, prefix="pk_live_xx"
            )

        async def _public_get(_):
            return _config_row(spam=spam)

        async def _audit_log(*_a, **_k):
            return None

        async def _find_existing(*_a, **_k):
            return None

        async def _create_contact(*_a, **_k):
            return SimpleNamespace(id=_CONTACT_ID)

        async def _create_lead(*_a, **_k):
            return SimpleNamespace(id=_LEAD_ID)

        class _NullCM:
            async def __aenter__(self_inner):
                return MagicMock()

            async def __aexit__(self_inner, *a):
                return False

        monkeypatch.setattr(submissions, "find_by_plain_key", _find_key)
        monkeypatch.setattr(submissions, "public_get_config", _public_get)
        monkeypatch.setattr(
            submissions,
            "check_per_key",
            lambda _p: RateLimitResult(
                allowed=True, remaining=100, retry_after=0.0
            ),
        )
        monkeypatch.setattr(
            submissions,
            "check_per_ip",
            lambda _ip: RateLimitResult(
                allowed=True, remaining=10, retry_after=0.0
            ),
        )
        monkeypatch.setattr(
            submissions, "find_existing_contact", _find_existing
        )
        monkeypatch.setattr(submissions, "create_contact", _create_contact)
        monkeypatch.setattr(submissions, "create_lead", _create_lead)
        monkeypatch.setattr(submissions, "async_session", lambda: _NullCM())
        monkeypatch.setattr(submissions.audit, "log", _audit_log)
        # The log_service.record call goes through both modules' names.
        monkeypatch.setattr(
            submissions.log_service, "record", self.log_capture
        )

    def find_log(self, outcome: EmbedSubmissionOutcome) -> Optional[dict]:
        for call in self.log_capture.calls:
            if call.get("outcome") == outcome:
                return call
        return None


@pytest.fixture
def harness_factory(monkeypatch):
    def _factory(*, spam=None):
        return _SubmitHarness(
            monkeypatch, org_id=uuid.uuid4(), spam=spam
        )

    return _factory


class TestSubmitWritesLog:
    @pytest.mark.asyncio
    async def test_accepted_writes_one_accepted_row(self, harness_factory):
        h = harness_factory()
        payload = _payload(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10)
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="203.0.113.5"
        )

        assert result.accepted is True
        row = h.find_log(EmbedSubmissionOutcome.accepted)
        assert row is not None
        assert row["lead_id"] == _LEAD_ID
        assert row["referrer"] == "https://customer.example/contact"
        assert row["landing_url"].startswith("https://customer.example")
        assert row["ip"] == "203.0.113.5"

    @pytest.mark.asyncio
    async def test_honeypot_writes_spam_row(self, harness_factory):
        h = harness_factory()
        payload = _payload(
            honeypot="trapped",
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="9.9.9.9"
        )

        row = h.find_log(EmbedSubmissionOutcome.rejected_spam)
        assert row is not None
        assert row["reason"] == "honeypot"
        assert row["lead_id"] is None if "lead_id" in row else True
        # And no accepted row was written.
        assert h.find_log(EmbedSubmissionOutcome.accepted) is None

    @pytest.mark.asyncio
    async def test_min_time_writes_spam_row(self, harness_factory):
        h = harness_factory()
        payload = _payload(rendered_at=datetime.now(timezone.utc))

        await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )

        row = h.find_log(EmbedSubmissionOutcome.rejected_spam)
        assert row is not None
        assert row["reason"] == "min_time"

    @pytest.mark.asyncio
    async def test_rate_limited_writes_row(self, harness_factory, monkeypatch):
        h = harness_factory()
        # Override the harness's allow-all rate limiter with a per-key reject.
        monkeypatch.setattr(
            submissions,
            "check_per_key",
            lambda _p: RateLimitResult(
                allowed=False, remaining=0, retry_after=60.0
            ),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await submissions.submit(
                payload=_payload(),
                header_key="pk_live_xx",
                ip="1.1.1.1",
            )
        assert exc.value.status_code == 429

        row = h.find_log(EmbedSubmissionOutcome.rate_limited)
        assert row is not None
        assert row["reason"] == "per_key"

    @pytest.mark.asyncio
    async def test_invalid_payload_writes_error_row(
        self, harness_factory
    ):
        h = harness_factory()
        # Force a validation failure: send a field name the config doesn't
        # know about. The widget config only declares full_name + phone.
        payload = _payload(
            email="bot@example.com",  # not configured
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await submissions.submit(
                payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
            )
        assert exc.value.status_code == 422

        row = h.find_log(EmbedSubmissionOutcome.invalid_payload)
        assert row is not None
        assert row["reason"]  # non-empty

    @pytest.mark.asyncio
    async def test_invalid_key_writes_no_row(self, harness_factory, monkeypatch):
        """Per the Step 9 decision: missing/invalid keys don't get logged
        — no org context to attach the row to."""
        h = harness_factory()
        # Override find_by_plain_key to return None (bad key).
        async def _no_key(plain, ip=None):
            return None

        monkeypatch.setattr(submissions, "find_by_plain_key", _no_key)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await submissions.submit(
                payload=_payload(),
                header_key="bad-key",
                ip="1.1.1.1",
            )
        assert exc.value.status_code == 401
        assert h.log_capture.calls == []
