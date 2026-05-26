"""Step 1 — integrations table + token storage tests.

Three groups:

  1. Pure `crypto` round-trip + Fernet semantics (no DB).
  2. `service.upsert / disconnect / decrypt_tokens` happy + idempotent
     paths via monkeypatched DB session (same pattern as embed Step 8/9
     tests — avoids the broken `seeded_admin` fixture).
  3. `IntegrationRead` schema projection — proves the encrypted-token
     columns are NOT serialised even if a router accidentally returned
     the raw SQLAlchemy row.

Like the embed tests, this skips DB round-trip tests because the
prod-style `async_session()` engine isn't safe to drive from
pytest-asyncio fixtures (asyncpg's "another operation in progress"
error on the second test using the fixture). Manual smoke covers
end-to-end DB writes — the unit tests cover the contract.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import InvalidToken

from src.app.core.integrations import crypto, service
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.schemas import (
    IntegrationRead,
    IntegrationUpsert,
)


# --- 1. crypto round-trip ------------------------------------------------


class TestCrypto:
    def test_roundtrip(self):
        assert crypto.decrypt(crypto.encrypt("hello")) == "hello"

    def test_ciphertext_differs_across_calls(self):
        # Fernet uses a fresh IV per encrypt — same plaintext yields
        # different ciphertexts, which is the whole point of an IV.
        a = crypto.encrypt("same-plaintext")
        b = crypto.encrypt("same-plaintext")
        assert a != b
        # But both decrypt back to the same value.
        assert crypto.decrypt(a) == crypto.decrypt(b) == "same-plaintext"

    def test_ciphertext_starts_with_fernet_prefix(self):
        # Fernet v1 tokens always start with 'gAAAA' (version byte +
        # 64-bit-timestamp encoded). Useful sanity for grepping the DB.
        assert crypto.encrypt("x").startswith("gAAAA")

    def test_decrypt_tampered_raises_invalid_token(self):
        ct = crypto.encrypt("payload")
        # Flip a byte in the middle — HMAC fails immediately.
        tampered = ct[:50] + ("A" if ct[50] != "A" else "B") + ct[51:]
        with pytest.raises(InvalidToken):
            crypto.decrypt(tampered)

    def test_encrypt_optional_passes_none_through(self):
        assert crypto.encrypt_optional(None) is None

    def test_decrypt_optional_passes_none_through(self):
        assert crypto.decrypt_optional(None) is None

    def test_optional_roundtrip(self):
        ct = crypto.encrypt_optional("refresh")
        assert ct is not None
        assert crypto.decrypt_optional(ct) == "refresh"


# --- 2. service-layer write paths via monkeypatched session --------------


_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


class _FakeResult:
    """`session.execute(...).scalar_one_or_none()` returns this."""

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return self

    def all(self):
        return [self._row] if self._row is not None else []


class _CapturingSession:
    """Minimal AsyncSession stand-in. Captures `session.add`'d rows
    and lets the service's commit / refresh flow run without a real DB.
    Returns a configurable row from `execute()` so we can simulate
    "no existing row" (new connect) vs. "existing row" (reconnect)."""

    def __init__(self, *, existing: Integration | None = None):
        self.existing = existing
        self.added: list = []
        self.committed = False

    async def execute(self, _stmt):
        return _FakeResult(self.existing)

    def add(self, row):
        self.added.append(row)
        # The service expects `await session.refresh(row)` to populate
        # an id — simulate that by setting one now if missing.
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        pass


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session; stub it to a no-op so the
    unit tests don't touch the real DB."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


class TestServiceUpsert:
    @pytest.mark.asyncio
    async def test_first_connect_creates_row_with_encrypted_tokens(self):
        session = _CapturingSession(existing=None)
        payload = IntegrationUpsert(
            provider="google_ads",
            account_id="123-456-7890",
            account_label="asha@example.com",
            access_token="plain-access-token",
            refresh_token="plain-refresh-token",
            token_expires_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            scopes=["https://www.googleapis.com/auth/adwords", "openid"],
        )

        row = await service.upsert(
            session, org_id=_ORG_ID, payload=payload, actor_id=_ACTOR_ID
        )

        assert len(session.added) == 1
        assert row.org_id == _ORG_ID
        assert row.provider == IntegrationProvider.google_ads
        assert row.status == IntegrationStatus.connected
        assert row.connected_at is not None
        assert row.connected_by == _ACTOR_ID
        assert row.account_label == "asha@example.com"
        assert row.scopes == [
            "https://www.googleapis.com/auth/adwords",
            "openid",
        ]
        # The encrypted columns must NOT contain the plaintext anywhere.
        assert row.access_token_enc is not None
        assert "plain-access-token" not in row.access_token_enc
        assert row.refresh_token_enc is not None
        assert "plain-refresh-token" not in row.refresh_token_enc
        # And decrypt_tokens recovers the original plaintext.
        access, refresh = service.decrypt_tokens(row)
        assert access == "plain-access-token"
        assert refresh == "plain-refresh-token"

    @pytest.mark.asyncio
    async def test_reconnect_updates_in_place(self):
        # Existing row from a previous connect.
        existing = Integration(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider=IntegrationProvider.google_ads,
            account_id="old-account",
            account_label="old@example.com",
            access_token_enc=crypto.encrypt("old-access"),
            refresh_token_enc=crypto.encrypt("old-refresh"),
            token_expires_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            scopes=["old-scope"],
            status=IntegrationStatus.expired,
            last_error="token expired",
            connected_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            connected_by=uuid.uuid4(),
        )
        session = _CapturingSession(existing=existing)
        payload = IntegrationUpsert(
            provider="google_ads",
            account_id="new-account",
            account_label="new@example.com",
            access_token="new-access",
            refresh_token="new-refresh",
            scopes=["new-scope"],
        )

        row = await service.upsert(
            session, org_id=_ORG_ID, payload=payload, actor_id=_ACTOR_ID
        )

        # No new row added — the existing one was mutated.
        assert session.added == []
        assert row is existing
        assert row.account_id == "new-account"
        assert row.account_label == "new@example.com"
        assert row.scopes == ["new-scope"]
        assert row.status == IntegrationStatus.connected
        assert row.last_error is None
        assert row.connected_by == _ACTOR_ID
        # New tokens decrypt to the new values; old tokens are gone.
        access, refresh = service.decrypt_tokens(row)
        assert access == "new-access"
        assert refresh == "new-refresh"

    @pytest.mark.asyncio
    async def test_refresh_token_optional(self):
        """Google sometimes omits the refresh_token on grant. The
        service must accept None and store NULL, not crash."""
        session = _CapturingSession(existing=None)
        payload = IntegrationUpsert(
            provider="google_ads",
            access_token="just-access",
            refresh_token=None,
        )
        row = await service.upsert(
            session, org_id=_ORG_ID, payload=payload, actor_id=_ACTOR_ID
        )
        assert row.refresh_token_enc is None
        access, refresh = service.decrypt_tokens(row)
        assert access == "just-access"
        assert refresh is None


class TestServiceDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_clears_tokens(self):
        existing = Integration(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider=IntegrationProvider.google_ads,
            access_token_enc=crypto.encrypt("a"),
            refresh_token_enc=crypto.encrypt("r"),
            token_expires_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            scopes=["s"],
            status=IntegrationStatus.connected,
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)

        row = await service.disconnect(
            session,
            provider=IntegrationProvider.google_ads,
            actor_id=_ACTOR_ID,
        )

        assert row is existing
        assert row.access_token_enc is None
        assert row.refresh_token_enc is None
        assert row.token_expires_at is None
        assert row.scopes is None
        assert row.status == IntegrationStatus.disconnected
        assert row.disconnected_at is not None
        assert row.disconnected_by == _ACTOR_ID

    @pytest.mark.asyncio
    async def test_disconnect_missing_row_returns_none(self):
        session = _CapturingSession(existing=None)
        row = await service.disconnect(
            session,
            provider=IntegrationProvider.google_ads,
            actor_id=_ACTOR_ID,
        )
        assert row is None
        assert session.committed is False

    @pytest.mark.asyncio
    async def test_disconnect_already_disconnected_is_noop(self):
        existing = Integration(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider=IntegrationProvider.google_ads,
            access_token_enc=None,
            refresh_token_enc=None,
            status=IntegrationStatus.disconnected,
        )
        session = _CapturingSession(existing=existing)
        row = await service.disconnect(
            session,
            provider=IntegrationProvider.google_ads,
            actor_id=_ACTOR_ID,
        )
        assert row is existing
        # No second commit — already disconnected.
        assert session.committed is False


class TestDecryptTokens:
    def test_raises_when_disconnected(self):
        row = Integration(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider=IntegrationProvider.google_ads,
            access_token_enc=None,
            status=IntegrationStatus.disconnected,
        )
        with pytest.raises(RuntimeError, match="no access token"):
            service.decrypt_tokens(row)


# --- 3. schema projection — encrypted tokens never leak ------------------


class TestIntegrationReadProjection:
    def test_no_encrypted_columns_in_response_shape(self):
        # Build a row with both encrypted columns populated, then
        # serialise it through IntegrationRead — the *_enc fields
        # must NOT appear in the output dict.
        row = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider="google_ads",
            account_id="123",
            account_label="asha@example.com",
            access_token_enc="ENCRYPTED-LEAK-CANARY",
            refresh_token_enc="ENCRYPTED-LEAK-CANARY",
            token_expires_at=datetime.now(timezone.utc),
            scopes=["s"],
            status="connected",
            last_error=None,
            connected_at=datetime.now(timezone.utc),
            connected_by=uuid.uuid4(),
            disconnected_at=None,
            disconnected_by=None,
            updated_at=datetime.now(timezone.utc),
        )

        dumped = IntegrationRead.model_validate(row).model_dump(mode="json")

        # Encrypted columns absent from the shape entirely.
        assert "access_token_enc" not in dumped
        assert "refresh_token_enc" not in dumped
        # The canary string doesn't appear anywhere in the serialised
        # response — extra paranoia in case a future schema change
        # accidentally exposes it.
        assert "LEAK-CANARY" not in str(dumped)
