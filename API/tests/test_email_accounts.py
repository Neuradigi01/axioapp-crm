"""Step 1 — email_accounts table + OAuth foundation tests.

Five groups:

  1. Token encryption roundtrip via the shared `core.integrations.crypto`
     module — proves Step 1's reuse-not-duplicate decision is sound.
  2. `service.upsert / disconnect / update_sync_state / decrypt_tokens`
     happy + idempotent paths via a `_CapturingSession` stand-in (same
     pattern as `test_integrations_table.py` — avoids the broken
     `seeded_admin` fixture from DR.7).
  3. `service.refresh_if_expired` — covers both the cache-hit path
     (no provider call) and the cache-miss path (provider's `refresh`
     fires, ciphertext re-persists).
  4. `oauth.issue_state / verify_state` — HMAC roundtrip + tamper +
     TTL.
  5. `EmailAccountRead` projection — proves the encrypted-token
     columns never leak even if a router accidentally returned the
     raw SQLAlchemy row.

Like the integrations tests, this skips DB round-trip tests because
the prod-style `async_session()` engine isn't safe to drive from
pytest-asyncio fixtures (asyncpg's "another operation in progress"
error on the second test using the fixture). Manual smoke covers
end-to-end DB writes — the unit tests cover the contract.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import pytest

from src.app.core.email import oauth, service
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email.oauth import (
    OAuthStateError,
    TokenSet,
    issue_state,
    register_provider,
    verify_state,
)
from src.app.core.email.schemas import EmailAccountRead, EmailAccountUpsert
from src.app.core.integrations import crypto


_ORG_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- shared monkeypatch: audit is best-effort and would otherwise
# open its own session and try to write to a real DB.
@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


# --- session stand-in ---------------------------------------------------


class _FakeResult:
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
    and lets the service's commit / refresh flow run without a real
    DB. Returns a configurable row from `execute()` to simulate
    "no existing row" vs "existing row"."""

    def __init__(self, *, existing: Optional[EmailAccount] = None):
        self.existing = existing
        self.added: list = []
        self.commits = 0

    async def execute(self, _stmt):
        return _FakeResult(self.existing)

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass


# --- 1. crypto reuse roundtrip ------------------------------------------


class TestCryptoReuse:
    """Step 1 deliberately reuses `core.integrations.crypto` rather
    than landing a parallel `core/email/crypto.py`. These tests
    document the contract and pin the behaviour so a future split
    is a conscious decision, not a silent regression."""

    def test_roundtrip(self):
        assert crypto.decrypt(crypto.encrypt("access-secret")) == "access-secret"

    def test_encrypt_optional_passes_none(self):
        assert crypto.encrypt_optional(None) is None
        assert crypto.decrypt_optional(None) is None

    def test_ciphertext_does_not_contain_plaintext(self):
        ct = crypto.encrypt("plain-leak-canary")
        assert "plain-leak-canary" not in ct


# --- 2. service write paths --------------------------------------------


class TestServiceUpsert:
    @pytest.mark.asyncio
    async def test_first_connect_creates_row_with_encrypted_tokens(self):
        session = _CapturingSession(existing=None)
        payload = EmailAccountUpsert(
            provider="gmail",
            external_account_id="asha@example.com",
            email_address="asha@example.com",
            display_name="Asha Patel",
            access_token="plain-access",
            refresh_token="plain-refresh",
            token_expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes_granted=[
                "https://www.googleapis.com/auth/gmail.modify",
                "openid",
            ],
        )

        row = await service.upsert(
            session,
            org_id=_ORG_ID,
            user_id=_USER_ID,
            payload=payload,
            actor_id=_ACTOR_ID,
        )

        assert len(session.added) == 1
        assert row.org_id == _ORG_ID
        assert row.user_id == _USER_ID
        assert row.provider == EmailAccountProvider.gmail
        assert row.external_account_id == "asha@example.com"
        assert row.email_address == "asha@example.com"
        assert row.display_name == "Asha Patel"
        assert row.sync_state == EmailAccountSyncState.pending
        assert row.connected_at is not None
        assert row.disconnected_at is None
        # Encrypted columns must NOT contain the plaintext.
        assert row.access_token_enc is not None
        assert "plain-access" not in row.access_token_enc
        assert row.refresh_token_enc is not None
        assert "plain-refresh" not in row.refresh_token_enc
        # And decrypt_tokens recovers the original plaintext.
        access, refresh = service.decrypt_tokens(row)
        assert access == "plain-access"
        assert refresh == "plain-refresh"

    @pytest.mark.asyncio
    async def test_reconnect_updates_in_place(self):
        existing = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="asha@example.com",
            email_address="asha@example.com",
            display_name=None,
            access_token_enc=crypto.encrypt("old-access"),
            refresh_token_enc=crypto.encrypt("old-refresh"),
            token_expires_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            scopes_granted=["old-scope"],
            sync_state=EmailAccountSyncState.error,
            last_sync_error="quota exceeded",
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)
        payload = EmailAccountUpsert(
            provider="gmail",
            external_account_id="asha@example.com",
            email_address="asha@example.com",
            display_name="Asha P.",
            access_token="new-access",
            refresh_token="new-refresh",
            scopes_granted=["new-scope"],
        )

        row = await service.upsert(
            session,
            org_id=_ORG_ID,
            user_id=_USER_ID,
            payload=payload,
            actor_id=_ACTOR_ID,
        )

        # Existing row mutated; no new row added.
        assert session.added == []
        assert row is existing
        assert row.display_name == "Asha P."
        assert row.scopes_granted == ["new-scope"]
        # Reconnect always lands as `pending` — daemon backfills again.
        assert row.sync_state == EmailAccountSyncState.pending
        assert row.last_sync_error is None
        # Disconnect history cleared.
        assert row.disconnected_at is None
        assert row.disconnected_by is None
        # Tokens replaced (new plaintext recoverable, old gone).
        access, refresh = service.decrypt_tokens(row)
        assert access == "new-access"
        assert refresh == "new-refresh"

    @pytest.mark.asyncio
    async def test_refresh_token_optional(self):
        """Microsoft on some tenant policies omits the refresh
        token. The service must accept None and store NULL."""
        session = _CapturingSession(existing=None)
        payload = EmailAccountUpsert(
            provider="microsoft",
            external_account_id="aad-object-id",
            email_address="user@contoso.com",
            access_token="just-access",
            refresh_token=None,
        )
        row = await service.upsert(
            session,
            org_id=_ORG_ID,
            user_id=_USER_ID,
            payload=payload,
            actor_id=_ACTOR_ID,
        )
        assert row.refresh_token_enc is None
        access, refresh = service.decrypt_tokens(row)
        assert access == "just-access"
        assert refresh is None


class TestServiceDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_clears_tokens(self):
        existing = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="asha@example.com",
            email_address="asha@example.com",
            access_token_enc=crypto.encrypt("a"),
            refresh_token_enc=crypto.encrypt("r"),
            token_expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            scopes_granted=["s"],
            sync_cursor="history-id-12345",
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)

        row = await service.disconnect(
            session, account_id=existing.id, actor_id=_ACTOR_ID
        )

        assert row is existing
        assert row.access_token_enc is None
        assert row.refresh_token_enc is None
        assert row.token_expires_at is None
        assert row.sync_cursor is None
        assert row.sync_state == EmailAccountSyncState.disconnected
        assert row.disconnected_at is not None
        assert row.disconnected_by == _ACTOR_ID

    @pytest.mark.asyncio
    async def test_disconnect_missing_returns_none(self):
        session = _CapturingSession(existing=None)
        row = await service.disconnect(
            session, account_id=uuid.uuid4(), actor_id=_ACTOR_ID
        )
        assert row is None
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_disconnect_already_disconnected_is_noop(self):
        existing = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=None,
            refresh_token_enc=None,
            scopes_granted=[],
            sync_state=EmailAccountSyncState.disconnected,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)
        row = await service.disconnect(
            session, account_id=existing.id, actor_id=_ACTOR_ID
        )
        assert row is existing
        # No second commit — already disconnected.
        assert session.commits == 0


class TestServiceUpdateSyncState:
    @pytest.mark.asyncio
    async def test_transition_to_live_clears_error_and_stamps_last_sync(self):
        existing = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("a"),
            scopes_granted=[],
            sync_state=EmailAccountSyncState.error,
            last_sync_error="provider 500",
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)

        row = await service.update_sync_state(
            session,
            account_id=existing.id,
            sync_state=EmailAccountSyncState.live,
            cursor="history-id-67890",
        )
        assert row is existing
        assert row.sync_state == EmailAccountSyncState.live
        assert row.last_sync_error is None
        assert row.last_sync_at is not None
        assert row.sync_cursor == "history-id-67890"

    @pytest.mark.asyncio
    async def test_transition_to_error_stamps_message(self):
        existing = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("a"),
            scopes_granted=[],
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=existing)

        row = await service.update_sync_state(
            session,
            account_id=existing.id,
            sync_state=EmailAccountSyncState.error,
            error="rate limited",
        )
        assert row.sync_state == EmailAccountSyncState.error
        assert row.last_sync_error == "rate limited"


class TestDecryptTokens:
    def test_raises_when_disconnected(self):
        row = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=None,
            scopes_granted=[],
            sync_state=EmailAccountSyncState.disconnected,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(RuntimeError, match="no access token"):
            service.decrypt_tokens(row)


# --- 3. refresh_if_expired ---------------------------------------------


class _FakeGmailProvider:
    name = "gmail"

    def __init__(self, *, fresh: TokenSet):
        self._fresh = fresh
        self.refresh_calls = 0

    def authorize_url(self, *, state, redirect_uri):  # pragma: no cover
        return "https://accounts.google.com/o/oauth2/v2/auth"

    async def exchange_code(self, *, code, redirect_uri):  # pragma: no cover
        return self._fresh

    async def refresh(self, *, refresh_token):
        self.refresh_calls += 1
        return self._fresh


@pytest.fixture(autouse=True)
def _reset_provider_registry():
    oauth._clear_registry_for_tests()
    yield
    oauth._clear_registry_for_tests()


class TestRefreshIfExpired:
    @pytest.mark.asyncio
    async def test_no_refresh_when_token_far_from_expiry(self):
        fresh = TokenSet(
            access_token="never-used",
            refresh_token="never-used",
            expires_in_seconds=3600,
            scopes_granted=["gmail.modify"],
        )
        provider = _FakeGmailProvider(fresh=fresh)
        register_provider(provider)

        account = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("current-access"),
            refresh_token_enc=crypto.encrypt("current-refresh"),
            token_expires_at=datetime.now(timezone.utc)
            + timedelta(hours=1),
            scopes_granted=["gmail.modify"],
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=account)

        tokens = await service.refresh_if_expired(
            session, account=account
        )

        assert provider.refresh_calls == 0
        assert tokens.access_token == "current-access"
        assert tokens.refresh_token == "current-refresh"

    @pytest.mark.asyncio
    async def test_refresh_fires_within_leeway(self):
        fresh = TokenSet(
            access_token="brand-new-access",
            refresh_token="brand-new-refresh",
            expires_in_seconds=3600,
            scopes_granted=["gmail.modify"],
        )
        provider = _FakeGmailProvider(fresh=fresh)
        register_provider(provider)

        # Token expires in 2 min — well inside the 5-min leeway.
        account = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("about-to-expire"),
            refresh_token_enc=crypto.encrypt("current-refresh"),
            token_expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=2),
            scopes_granted=["gmail.modify"],
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=account)

        tokens = await service.refresh_if_expired(
            session, account=account
        )

        assert provider.refresh_calls == 1
        assert tokens.access_token == "brand-new-access"
        # Ciphertext on the row should now decrypt to the NEW token,
        # not the prior one.
        access, refresh = service.decrypt_tokens(account)
        assert access == "brand-new-access"
        assert refresh == "brand-new-refresh"

    @pytest.mark.asyncio
    async def test_refresh_without_refresh_token_raises(self):
        provider = _FakeGmailProvider(
            fresh=TokenSet(
                access_token="x",
                refresh_token=None,
                expires_in_seconds=60,
                scopes_granted=[],
            )
        )
        register_provider(provider)

        account = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("a"),
            refresh_token_enc=None,
            token_expires_at=datetime.now(timezone.utc)
            - timedelta(minutes=1),
            scopes_granted=[],
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=account)

        with pytest.raises(RuntimeError, match="no refresh token"):
            await service.refresh_if_expired(session, account=account)
        assert provider.refresh_calls == 0

    @pytest.mark.asyncio
    async def test_refresh_with_no_registered_provider_raises(self):
        # Registry is empty (autouse fixture cleared it).
        account = EmailAccount(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider=EmailAccountProvider.gmail,
            external_account_id="x",
            email_address="x@example.com",
            access_token_enc=crypto.encrypt("a"),
            refresh_token_enc=crypto.encrypt("r"),
            token_expires_at=datetime.now(timezone.utc)
            - timedelta(minutes=1),
            scopes_granted=[],
            sync_state=EmailAccountSyncState.live,
            daily_sent_count=0,
            daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session = _CapturingSession(existing=account)
        with pytest.raises(RuntimeError, match="no OAuth provider"):
            await service.refresh_if_expired(session, account=account)


# --- 4. OAuth state signing --------------------------------------------


class TestOAuthState:
    def test_roundtrip(self):
        s = issue_state(
            user_id=str(_USER_ID),
            org_id=str(_ORG_ID),
            provider="gmail",
        )
        payload = verify_state(s)
        assert payload.user_id == str(_USER_ID)
        assert payload.org_id == str(_ORG_ID)
        assert payload.provider == "gmail"

    def test_tampered_state_rejected(self):
        s = issue_state(
            user_id=str(_USER_ID),
            org_id=str(_ORG_ID),
            provider="gmail",
        )
        body, sig = s.rsplit(".", 1)
        # Flip a byte in the signature.
        bad_sig = ("a" if sig[0] != "a" else "b") + sig[1:]
        with pytest.raises(OAuthStateError, match="signature invalid"):
            verify_state(f"{body}.{bad_sig}")

    def test_malformed_state_rejected(self):
        with pytest.raises(OAuthStateError):
            verify_state("not-a-state")
        with pytest.raises(OAuthStateError):
            verify_state("")

    def test_expired_state_rejected(self, monkeypatch):
        # Issue with a back-dated clock so the state is "old".
        real_time = time.time
        # 11 minutes ago — past the 10-minute TTL.
        past = real_time() - (60 * 11)
        monkeypatch.setattr(oauth.time, "time", lambda: past)
        s = issue_state(
            user_id=str(_USER_ID),
            org_id=str(_ORG_ID),
            provider="gmail",
        )
        monkeypatch.setattr(oauth.time, "time", real_time)
        with pytest.raises(OAuthStateError, match="expired"):
            verify_state(s)


# --- 5. schema projection — encrypted tokens never leak ---------------


class TestEmailAccountReadProjection:
    def test_no_encrypted_columns_in_response_shape(self):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            user_id=_USER_ID,
            provider="gmail",
            external_account_id="x@example.com",
            email_address="x@example.com",
            display_name="X",
            access_token_enc="ENCRYPTED-LEAK-CANARY-ACCESS",
            refresh_token_enc="ENCRYPTED-LEAK-CANARY-REFRESH",
            token_expires_at=datetime.now(timezone.utc),
            scopes_granted=["s"],
            sync_state="live",
            last_sync_at=datetime.now(timezone.utc),
            last_sync_error=None,
            daily_sent_count=0,
            daily_sent_reset_at=datetime.now(timezone.utc),
            connected_at=datetime.now(timezone.utc),
            disconnected_at=None,
            disconnected_by=None,
        )

        dumped = EmailAccountRead.model_validate(row).model_dump(mode="json")

        # Encrypted columns absent from the shape entirely.
        assert "access_token_enc" not in dumped
        assert "refresh_token_enc" not in dumped
        # And the canary strings don't appear anywhere serialised.
        assert "LEAK-CANARY" not in str(dumped)
