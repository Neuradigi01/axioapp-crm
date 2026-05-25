"""Step 8 — widget spam-gate unit tests.

Three groups:

  1. `_passes_min_fill_time` pure-function tests — covers the
     min-time / future / clock-skew / missing-rendered_at branches.

  2. `recaptcha.verify_token` tests with a mocked `httpx.AsyncClient` —
     covers success / low-score / action-mismatch / non-200 / network
     / parse-failure paths.

  3. `submissions.submit` integration tests — monkeypatches the DB-
     touching helpers (`find_by_plain_key`, `public_get_config`,
     `create_contact`, `create_lead`, `find_existing_contact`,
     `audit.log`) and the rate-limiter so each spam gate can be
     exercised in isolation. Covers honeypot / min-time / reCAPTCHA
     happy + reject branches + the all-gates-pass path.

The fixture stack here avoids the `seeded_admin` conftest fixture
(known-broken in this branch) by stubbing every collaborator the
submission service touches.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.core.embed import recaptcha, submissions
from src.app.core.embed.rate_limit import RateLimitResult
from src.app.core.embed.schemas import (
    EmbedSubmission,
    SubmissionAttribution,
    WidgetConfigDocument,
    WidgetConfigField,
    WidgetConfigPublicDocument,
    WidgetConfigSpamProtection,
)


# --- 1. min-fill-time pure function ---------------------------------------


def _payload_defaults(**overrides) -> EmbedSubmission:
    """Build a minimum-viable EmbedSubmission for unit tests."""
    base = dict(
        full_name="Asha Reddy",
        phone="+91 9000000000",
        attribution=SubmissionAttribution(),
    )
    base.update(overrides)
    return EmbedSubmission(**base)


class TestMinFillTime:
    def test_none_rendered_at_fails(self):
        assert (
            submissions._passes_min_fill_time(
                rendered_at=None, min_fill_time_ms=2000
            )
            is False
        )

    def test_future_rendered_at_fails(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert (
            submissions._passes_min_fill_time(
                rendered_at=future, min_fill_time_ms=2000
            )
            is False
        )

    def test_too_recent_fails(self):
        recent = datetime.now(timezone.utc) - timedelta(milliseconds=500)
        assert (
            submissions._passes_min_fill_time(
                rendered_at=recent, min_fill_time_ms=2000
            )
            is False
        )

    def test_more_than_24h_old_fails(self):
        ancient = datetime.now(timezone.utc) - timedelta(hours=25)
        assert (
            submissions._passes_min_fill_time(
                rendered_at=ancient, min_fill_time_ms=2000
            )
            is False
        )

    def test_within_window_passes(self):
        rendered = datetime.now(timezone.utc) - timedelta(seconds=5)
        assert (
            submissions._passes_min_fill_time(
                rendered_at=rendered, min_fill_time_ms=2000
            )
            is True
        )

    def test_naive_datetime_treated_as_utc(self):
        # Pydantic strips tz on some inputs; the helper must normalise.
        rendered = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) - timedelta(seconds=5)
        assert rendered.tzinfo is None
        assert (
            submissions._passes_min_fill_time(
                rendered_at=rendered, min_fill_time_ms=2000
            )
            is True
        )


# --- 2. reCAPTCHA verify_token --------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int
    body: dict | None = None
    raise_on_json: bool = False
    text: str = ""

    def json(self):
        if self.raise_on_json:
            raise ValueError("not json")
        return self.body


class _FakeClient:
    """Stand-in for httpx.AsyncClient — captures the POST + returns a
    pre-canned response (or raises)."""

    def __init__(
        self,
        *,
        response: Optional[_FakeResponse] = None,
        raise_exc: Optional[Exception] = None,
    ):
        self._response = response
        self._raise = raise_exc
        self.last_url: Optional[str] = None
        self.last_data: Optional[dict] = None

    async def post(self, url, data=None):
        self.last_url = url
        self.last_data = data
        if self._raise is not None:
            raise self._raise
        return self._response


class TestRecaptchaVerify:
    @pytest.mark.asyncio
    async def test_success_high_score(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200,
                body={"success": True, "score": 0.9, "action": "submit"},
            )
        )
        ok = await recaptcha.verify_token(
            token="t", secret="s", http_client=client
        )
        assert ok is True
        assert client.last_url == recaptcha.VERIFY_URL
        assert client.last_data == {"secret": "s", "response": "t"}

    @pytest.mark.asyncio
    async def test_remote_ip_passed_through(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200,
                body={"success": True, "score": 0.9, "action": "submit"},
            )
        )
        await recaptcha.verify_token(
            token="t", secret="s", remote_ip="1.2.3.4", http_client=client
        )
        assert client.last_data == {
            "secret": "s",
            "response": "t",
            "remoteip": "1.2.3.4",
        }

    @pytest.mark.asyncio
    async def test_success_false_rejected(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200,
                body={"success": False, "error-codes": ["invalid-input-response"]},
            )
        )
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_low_score_rejected(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200,
                body={"success": True, "score": 0.2, "action": "submit"},
            )
        )
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_action_mismatch_rejected(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200,
                body={"success": True, "score": 0.9, "action": "login"},
            )
        )
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_non_200_status_rejected(self):
        client = _FakeClient(
            response=_FakeResponse(status_code=500, body={}, text="boom")
        )
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_non_json_body_rejected(self):
        client = _FakeClient(
            response=_FakeResponse(
                status_code=200, body=None, raise_on_json=True
            )
        )
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_network_error_fails_closed(self):
        client = _FakeClient(raise_exc=httpx.ConnectError("dns"))
        assert (
            await recaptcha.verify_token(
                token="t", secret="s", http_client=client
            )
            is False
        )


# --- 3. submissions.submit integration ------------------------------------


_KEY_ID = uuid.uuid4()
_ORG_ID = uuid.uuid4()
_LEAD_ID = uuid.uuid4()
_CONTACT_ID = uuid.uuid4()


def _fake_key_row():
    return SimpleNamespace(
        id=_KEY_ID,
        org_id=_ORG_ID,
        prefix="pk_live_xx",
    )


def _config_row(*, spam: WidgetConfigSpamProtection | None = None):
    """A pretend config row with `.config` JSONB."""
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


def _allow():
    return RateLimitResult(allowed=True, remaining=100, retry_after=0.0)


class _SubmitHarness:
    """Bundle every monkeypatch the submit-flow tests need.

    Yields an object exposing the audit captures so assertions are
    one-liners.
    """

    def __init__(self, monkeypatch, *, spam=None):
        self.monkeypatch = monkeypatch
        self.audit_events: list[dict] = []
        self.created_leads: list = []
        self.created_contacts: list = []

        async def _find_key(plain, ip=None):
            return _fake_key_row()

        async def _public_get(org_id):
            return _config_row(spam=spam)

        async def _audit_log(action, **kwargs):
            self.audit_events.append({"action": action, **kwargs})

        async def _find_existing(session, *, org_id, phone, email):
            return None

        async def _create_contact(session, *, org_id, payload, **_kwargs):
            # `**_kwargs` absorbs `require_all_required` and any future
            # opt-in parameters added to the real service signature.
            contact = SimpleNamespace(id=_CONTACT_ID)
            self.created_contacts.append(contact)
            return contact

        async def _create_lead(session, *, org_id, payload, **_kwargs):
            lead = SimpleNamespace(id=_LEAD_ID)
            self.created_leads.append(lead)
            return lead

        # async_session is used in a `async with` block; stub it with a
        # tiny async context manager that yields a sentinel session.
        class _NullCM:
            async def __aenter__(self_inner):
                return MagicMock()

            async def __aexit__(self_inner, *a):
                return False

        monkeypatch.setattr(submissions, "find_by_plain_key", _find_key)
        monkeypatch.setattr(submissions, "public_get_config", _public_get)
        monkeypatch.setattr(submissions, "check_per_key", lambda _p: _allow())
        monkeypatch.setattr(submissions, "check_per_ip", lambda _ip: _allow())
        monkeypatch.setattr(
            submissions, "find_existing_contact", _find_existing
        )
        monkeypatch.setattr(submissions, "create_contact", _create_contact)
        monkeypatch.setattr(submissions, "create_lead", _create_lead)
        monkeypatch.setattr(submissions, "async_session", lambda: _NullCM())
        # audit.log is invoked via the `audit` module reference.
        monkeypatch.setattr(submissions.audit, "log", _audit_log)


@pytest.fixture
def harness_factory(monkeypatch):
    def _factory(*, spam=None):
        return _SubmitHarness(monkeypatch, spam=spam)

    return _factory


class TestSubmitSpamGates:
    @pytest.mark.asyncio
    async def test_honeypot_silent_drops_and_audits(self, harness_factory):
        h = harness_factory()
        payload = _payload_defaults(
            honeypot="trapped",
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )

        assert result.accepted is False
        assert result.lead_id is None
        assert h.created_leads == []
        assert len(h.audit_events) == 1
        assert h.audit_events[0]["action"] == "embed.submission.rejected_spam"
        assert h.audit_events[0]["after"]["reason"] == "honeypot"
        # IP hash present, raw IP not stored:
        assert h.audit_events[0]["after"]["ip_hash"]
        assert "1.1.1.1" not in str(h.audit_events[0]["after"])

    @pytest.mark.asyncio
    async def test_min_time_too_fast_silent_drops(self, harness_factory):
        h = harness_factory()
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc)
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is False
        assert h.created_leads == []
        assert h.audit_events[-1]["after"]["reason"] == "min_time"

    @pytest.mark.asyncio
    async def test_min_time_future_silent_drops(self, harness_factory):
        h = harness_factory()
        payload = _payload_defaults(
            rendered_at=datetime(2099, 1, 1, tzinfo=timezone.utc)
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is False
        assert h.audit_events[-1]["after"]["reason"] == "min_time"

    @pytest.mark.asyncio
    async def test_min_time_skipped_when_disabled(self, harness_factory):
        h = harness_factory(
            spam=WidgetConfigSpamProtection(min_fill_time_ms=0)
        )
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc)
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is True
        assert h.created_leads == [SimpleNamespace(id=_LEAD_ID)]

    @pytest.mark.asyncio
    async def test_recaptcha_missing_token_when_enabled(
        self, harness_factory
    ):
        spam = WidgetConfigSpamProtection(
            recaptcha_enabled=True,
            recaptcha_site_key="6Lc-site",
            recaptcha_secret_key="6Lc-secret",
        )
        h = harness_factory(spam=spam)
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is False
        assert h.audit_events[-1]["after"]["reason"] == "recaptcha_invalid"

    @pytest.mark.asyncio
    async def test_recaptcha_low_score_silent_drops(
        self, harness_factory, monkeypatch
    ):
        spam = WidgetConfigSpamProtection(
            recaptcha_enabled=True,
            recaptcha_site_key="6Lc-site",
            recaptcha_secret_key="6Lc-secret",
        )
        h = harness_factory(spam=spam)
        verify_mock = AsyncMock(return_value=False)
        monkeypatch.setattr(
            submissions, "verify_recaptcha_token", verify_mock
        )
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            recaptcha_token="t",
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is False
        assert h.audit_events[-1]["after"]["reason"] == "recaptcha_low_score"
        verify_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recaptcha_happy_path(
        self, harness_factory, monkeypatch
    ):
        spam = WidgetConfigSpamProtection(
            recaptcha_enabled=True,
            recaptcha_site_key="6Lc-site",
            recaptcha_secret_key="6Lc-secret",
        )
        h = harness_factory(spam=spam)
        monkeypatch.setattr(
            submissions,
            "verify_recaptcha_token",
            AsyncMock(return_value=True),
        )
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            recaptcha_token="t",
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is True
        assert result.lead_id == _LEAD_ID
        # Final audit event is the `accepted` row, not a spam rejection.
        assert h.audit_events[-1]["action"] == "embed.submission.accepted"

    @pytest.mark.asyncio
    async def test_all_gates_pass_happy_path(self, harness_factory):
        h = harness_factory()
        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )
        assert result.accepted is True
        assert result.lead_id == _LEAD_ID
        assert len(h.created_contacts) == 1
        assert len(h.created_leads) == 1


# --- Step 10: custom-field routing ----------------------------------------


def _config_row_with_custom_field(*, with_lead_custom: bool = False):
    """A config that exposes one standard field plus a contact-entity
    custom `address` text field. When `with_lead_custom=True`, also
    includes a lead-entity custom `companyname` text field — mirrors
    the Owner adding both via the picker."""
    fields = [
        WidgetConfigField(
            key="full_name", label="Name", required=True, order=0,
            field_type="text", field_source="standard", entity="contact",
        ),
        WidgetConfigField(
            key="phone", label="Phone", required=True, order=1,
            field_type="tel", field_source="standard", entity="contact",
        ),
        WidgetConfigField(
            key="address", label="Address", required=False, order=2,
            field_type="text", field_source="custom", entity="contact",
        ),
    ]
    if with_lead_custom:
        fields.append(
            WidgetConfigField(
                key="companyname", label="Company", required=False,
                order=3, field_type="text", field_source="custom",
                entity="lead",
            )
        )
    doc = WidgetConfigDocument(fields=fields)
    return SimpleNamespace(config=doc.model_dump(mode="json"))


class TestCustomFieldRouting:
    @pytest.mark.asyncio
    async def test_custom_field_value_routes_into_contact_custom_data(
        self, monkeypatch
    ):
        # Build our own harness so we can intercept the ContactCreate
        # payload and inspect what custom_data was passed in.
        created_payloads: list = []

        async def _find_key(plain, ip=None):
            return SimpleNamespace(
                id=_KEY_ID, org_id=_ORG_ID, prefix="pk_live_xx"
            )

        async def _public_get(_):
            return _config_row_with_custom_field()

        async def _audit_log(*_a, **_k):
            return None

        async def _record_log(*_a, **_k):
            return None

        async def _find_existing(*_a, **_k):
            return None

        async def _create_contact(session, *, org_id, payload, **_kwargs):
            created_payloads.append(payload)
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
        monkeypatch.setattr(
            submissions.log_service, "record", _record_log
        )

        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            custom_data={"address": "42 MG Road, Pune"},
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )

        assert result.accepted is True
        assert len(created_payloads) == 1
        assert created_payloads[0].custom_data == {
            "address": "42 MG Road, Pune"
        }

    @pytest.mark.asyncio
    async def test_lead_entity_custom_field_routes_into_lead_custom_data(
        self, monkeypatch
    ):
        # Owner exposes a lead-entity `companyname` custom field on the
        # widget. Submitted value must land in the LEAD's custom_data
        # (not the contact's).
        contact_payloads: list = []
        lead_payloads: list = []

        async def _find_key(plain, ip=None):
            return SimpleNamespace(
                id=_KEY_ID, org_id=_ORG_ID, prefix="pk_live_xx"
            )

        async def _public_get(_):
            return _config_row_with_custom_field(with_lead_custom=True)

        async def _audit_log(*_a, **_k):
            return None

        async def _record_log(*_a, **_k):
            return None

        async def _find_existing(*_a, **_k):
            return None

        async def _create_contact(session, *, org_id, payload, **_kwargs):
            contact_payloads.append(payload)
            return SimpleNamespace(id=_CONTACT_ID)

        async def _create_lead(session, *, org_id, payload, **_kwargs):
            lead_payloads.append(payload)
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
        monkeypatch.setattr(
            submissions.log_service, "record", _record_log
        )

        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            custom_data={
                "address": "42 MG Road, Pune",
                "companyname": "Acme Furniture Pvt Ltd",
            },
        )

        result = await submissions.submit(
            payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
        )

        assert result.accepted is True
        # Address lives on contact, companyname lives on lead.
        assert len(contact_payloads) == 1
        assert contact_payloads[0].custom_data == {
            "address": "42 MG Road, Pune"
        }
        assert len(lead_payloads) == 1
        assert lead_payloads[0].custom_data == {
            "companyname": "Acme Furniture Pvt Ltd"
        }

    @pytest.mark.asyncio
    async def test_unconfigured_custom_field_rejected_422(
        self, monkeypatch
    ):
        # Org's config does NOT include `internal_notes` — visitor's
        # custom_data payload contains it. Must be rejected so a forged
        # request can't write to fields the Owner hasn't opted in.
        async def _find_key(plain, ip=None):
            return SimpleNamespace(
                id=_KEY_ID, org_id=_ORG_ID, prefix="pk_live_xx"
            )

        async def _public_get(_):
            return _config_row_with_custom_field()  # only `address` exposed

        async def _record_log(*_a, **_k):
            return None

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
            submissions.log_service, "record", _record_log
        )

        from fastapi import HTTPException

        payload = _payload_defaults(
            rendered_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            custom_data={"internal_notes": "forged"},
        )

        with pytest.raises(HTTPException) as exc:
            await submissions.submit(
                payload=payload, header_key="pk_live_xx", ip="1.1.1.1"
            )
        assert exc.value.status_code == 422
        assert "internal_notes" in str(exc.value.detail)


# --- 4. public projection strips the secret -------------------------------


class TestPublicProjection:
    def test_recaptcha_secret_never_leaks(self):
        full = WidgetConfigDocument(
            fields=[
                WidgetConfigField(
                    key="full_name", label="Name", required=True, order=0,
                    field_type="text",
                )
            ],
            spam_protection=WidgetConfigSpamProtection(
                recaptcha_enabled=True,
                recaptcha_site_key="6Lc-site",
                recaptcha_secret_key="6Lc-secret-HIDDEN",
            ),
        )
        public = WidgetConfigPublicDocument.model_validate(
            full.model_dump(mode="json")
        )
        dump = public.model_dump(mode="json")
        # The public projection's spam_protection has no secret_key field.
        assert "recaptcha_secret_key" not in dump["spam_protection"]
        # And the secret string doesn't appear anywhere in the response.
        assert "HIDDEN" not in str(dump)
        # But the site key (public by design) IS present.
        assert dump["spam_protection"]["recaptcha_site_key"] == "6Lc-site"

    def test_enable_without_keys_rejected(self):
        with pytest.raises(ValueError, match="requires both"):
            WidgetConfigSpamProtection(recaptcha_enabled=True)
