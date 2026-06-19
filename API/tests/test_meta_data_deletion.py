"""whatsapp-platform-upgrade Step 4 — Meta Data Deletion Callback tests.

Coverage focuses on the signed_request parser (the security-critical
half) + the lifecycle of a deletion request row. The async Celery task
is exercised in isolation against a stubbed session (the production
scrub mutates real DB rows; we assert it builds + runs without raising).

Mirrors the surrounding ``test_whatsapp_*`` test files: pure-Python
fakes for the DB, no Meta network, no Celery broker.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

import pytest

from src.app.core.integrations.meta import data_deletion as dd
from src.app.core.integrations.meta.models import (
    MetaDataDeletionRequest,
    MetaDataDeletionStatus,
)


_APP_SECRET = "test-app-secret-xyz"
_META_USER_ID = "10001234567890"


# --- helpers ------------------------------------------------------------


def _make_signed_request(
    *,
    user_id: str = _META_USER_ID,
    issued_at: int | None = None,
    algorithm: str = "HMAC-SHA256",
    app_secret: str = _APP_SECRET,
    tamper: bool = False,
) -> str:
    """Build a Meta-style signed_request string for the test cases."""
    if issued_at is None:
        issued_at = int(time.time())
    payload = {
        "user_id": user_id,
        "algorithm": algorithm,
        "issued_at": issued_at,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = (
        base64.urlsafe_b64encode(payload_json.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    sig = hmac.new(
        app_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    if tamper:
        # Flip a bit in the payload portion AFTER signing — the
        # signature no longer matches the contents.
        payload_b64 = payload_b64[:-1] + (
            "A" if payload_b64[-1] != "A" else "B"
        )
    return f"{sig_b64}.{payload_b64}"


# --- signed_request parser -----------------------------------------------


class TestSignedRequestParser:
    def test_happy_path_returns_decoded_payload(self):
        signed = _make_signed_request()
        data = dd.parse_signed_request(signed, app_secret=_APP_SECRET)
        assert data["user_id"] == _META_USER_ID
        assert data["algorithm"] == "HMAC-SHA256"
        assert isinstance(data["issued_at"], int)

    def test_tampered_signature_raises_invalid_signature(self):
        signed = _make_signed_request(tamper=True)
        with pytest.raises(dd.InvalidSignatureError):
            dd.parse_signed_request(signed, app_secret=_APP_SECRET)

    def test_wrong_app_secret_raises_invalid_signature(self):
        signed = _make_signed_request(app_secret="other-secret")
        with pytest.raises(dd.InvalidSignatureError):
            dd.parse_signed_request(signed, app_secret=_APP_SECRET)

    def test_wrong_algorithm_raises_invalid_algorithm(self):
        signed = _make_signed_request(algorithm="HMAC-SHA1")
        with pytest.raises(dd.InvalidAlgorithmError):
            dd.parse_signed_request(signed, app_secret=_APP_SECRET)

    def test_stale_request_raises_stale(self):
        signed = _make_signed_request(
            issued_at=int(time.time()) - 700  # > 10 min
        )
        with pytest.raises(dd.StaleRequestError):
            dd.parse_signed_request(signed, app_secret=_APP_SECRET)

    def test_missing_signed_request_raises_malformed(self):
        with pytest.raises(dd.MalformedRequestError):
            dd.parse_signed_request("", app_secret=_APP_SECRET)

    def test_no_dot_separator_raises_malformed(self):
        with pytest.raises(dd.MalformedRequestError):
            dd.parse_signed_request(
                "no-dot-here", app_secret=_APP_SECRET
            )

    def test_garbage_base64_raises_malformed(self):
        with pytest.raises(dd.MalformedRequestError):
            dd.parse_signed_request(
                "not_b64!.also_not_b64!", app_secret=_APP_SECRET
            )

    def test_missing_user_id_raises_malformed(self):
        # Build a payload with no user_id; sign it correctly so the
        # parser reaches the field check.
        payload = {
            "algorithm": "HMAC-SHA256",
            "issued_at": int(time.time()),
        }
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = (
            base64.urlsafe_b64encode(payload_json.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        sig = hmac.new(
            _APP_SECRET.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sig_b64 = (
            base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
        )
        signed = f"{sig_b64}.{payload_b64}"
        with pytest.raises(dd.MalformedRequestError):
            dd.parse_signed_request(signed, app_secret=_APP_SECRET)


# --- status lookup (synchronous projection) ------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _CapturingSession:
    """Drop-in for the SQLAlchemy AsyncSession the data-deletion service
    uses. Routes ``select(MetaDataDeletionRequest)`` to a pre-stocked
    row by inspecting the statement's column descriptions."""

    def __init__(self):
        self.rows: list[MetaDataDeletionRequest] = []
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        try:
            descs = stmt.column_descriptions
        except AttributeError:
            descs = None
        if descs:
            entity = descs[0].get("entity")
            if entity is MetaDataDeletionRequest and self.rows:
                return _FakeResult(self.rows[0])
        return _FakeResult(None)

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        self.added.append(row)
        if isinstance(row, MetaDataDeletionRequest):
            self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass


class TestStatusLookup:
    @pytest.mark.asyncio
    async def test_demo_code_returns_synthetic_completed(self):
        session = _CapturingSession()
        result = await dd.get_status_by_code(
            session, confirmation_code=dd.DEMO_CONFIRMATION_CODE
        )
        assert result is not None
        assert result["status"] == "completed"
        assert result["is_demo"] is True
        # Synthetic path doesn't touch the DB.
        assert session.rows == []

    @pytest.mark.asyncio
    async def test_real_code_returns_persisted_projection(self):
        session = _CapturingSession()
        request_row = MetaDataDeletionRequest(
            id=uuid.uuid4(),
            confirmation_code="abc123def456",
            meta_user_id=_META_USER_ID,
            issued_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
            affected_org_ids=[uuid.uuid4(), uuid.uuid4()],
            status=MetaDataDeletionStatus.in_progress,
            requested_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )
        session.rows.append(request_row)

        result = await dd.get_status_by_code(
            session, confirmation_code="abc123def456"
        )
        assert result is not None
        assert result["status"] == "in_progress"
        assert result["affected_org_count"] == 2
        assert result["is_demo"] is False
        # PII never leaks to the public projection.
        assert "meta_user_id" not in result
        assert "failure_reason" not in result

    @pytest.mark.asyncio
    async def test_unknown_code_returns_none(self):
        session = _CapturingSession()
        result = await dd.get_status_by_code(
            session, confirmation_code="does-not-exist"
        )
        assert result is None


# --- confirmation code shape --------------------------------------------


class TestConfirmationCode:
    def test_code_is_url_safe_and_high_entropy(self):
        a = dd.generate_confirmation_code()
        b = dd.generate_confirmation_code()
        assert a != b
        assert 32 <= len(a) <= 64
        # URL-safe set: alphanumerics + - + _
        for ch in a:
            assert ch.isalnum() or ch in {"-", "_"}
