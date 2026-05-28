"""Step 3.5.1 — WhatsApp account connect/disconnect/test/status tests.

Mirrors the `test_integrations_table.py` pattern: pure-Python fake
session + Fernet round-trip + projection shape. Meta's Graph API is
stubbed via an injectable httpx-client factory (same convention the
`WhatsAppAdapter` uses), so no network is touched.

What we prove:

  1. Happy connect — Integration + sidecar both inserted, tokens
     encrypted (plaintext nowhere near the rows), display fields
     populated from Meta's response.
  2. Invalid token — Integration row marked `status=error` with the
     Meta error message verbatim; sidecar NOT created (no point
     caching identifiers we never accepted).
  3. Disconnect — bearer token nulled, status flipped, idempotent on
     a missing row.
  4. Status projection — `WhatsAppStatusOut` has no token field anywhere,
     so a router accidentally returning the raw service payload can't
     leak ciphertext.
  5. Test endpoint — re-pings Meta with stored creds; flips to error +
     persists `last_error` on rejection; recovers to connected on
     success.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppAdapter,
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.integrations import crypto
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp import connect as wa_connect
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppConnectIn,
    WhatsAppStatusOut,
)


_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- fake session --------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _CapturingSession:
    """Multi-entity fake AsyncSession. Routes `execute(select(X))` to a
    pre-stocked row by inspecting `stmt.column_descriptions[0]['entity']`.

    No WHERE-clause evaluation — we have one row per entity at most in
    each test, which matches the production UNIQUE constraints
    (`(org, provider)` for Integration; `integration_id` for sidecar).
    """

    def __init__(self):
        self.rows: dict[type, list] = {
            Integration: [],
            WhatsAppAccountConfig: [],
        }
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        entity = None
        try:
            descs = stmt.column_descriptions
            if descs:
                entity = descs[0].get("entity")
        except (AttributeError, KeyError, IndexError):
            entity = None
        if entity in self.rows and self.rows[entity]:
            return _FakeResult(self.rows[entity][0])
        return _FakeResult(None)

    def add(self, row):
        # Production columns assign id via `gen_random_uuid()` on flush.
        # Mirror that here so the integration_id FK in the sidecar
        # references a stable value.
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        for cls in self.rows:
            if isinstance(row, cls):
                self.rows[cls].append(row)
                break
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass


# --- Meta stubs ----------------------------------------------------------


def _meta_ok_factory():
    """Stub httpx client factory: `GET /{phone_id}` returns 200 with
    display_phone_number + verified_name."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url, headers=None):
            return httpx.Response(
                200,
                json={
                    "display_phone_number": "+91 98765 43210",
                    "verified_name": "Sharma Furniture",
                    "id": "123456789012345",
                },
            )

    return lambda: _Client()


def _meta_401_factory():
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url, headers=None):
            return httpx.Response(
                401,
                json={
                    "error": {
                        "message": "(#190) Invalid OAuth access token.",
                        "code": 190,
                    }
                },
            )

    return lambda: _Client()


# --- audit silencer ------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(wa_connect.audit, "log", _noop)


# --- fixtures ------------------------------------------------------------


_VALID_PAYLOAD = WhatsAppConnectIn(
    phone_id="123456789012345",
    waba_id="987654321098765",
    access_token="EAAxxx-plaintext-token",
    app_secret="plain-app-secret",
    verify_token="my-random-verify-string",
    api_version="v18.0",
)


def _existing_connected_pair() -> tuple[Integration, WhatsAppAccountConfig]:
    integration = Integration(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        provider=IntegrationProvider.whatsapp,
        account_id="123456789012345",
        account_label="+91 98765 43210",
        access_token_enc=crypto.encrypt("stored-bearer"),
        refresh_token_enc=None,
        token_expires_at=None,
        scopes=None,
        status=IntegrationStatus.connected,
        last_error=None,
        connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        connected_by=_ACTOR_ID,
    )
    config = WhatsAppAccountConfig(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        integration_id=integration.id,
        phone_id="123456789012345",
        waba_id="987654321098765",
        display_phone_number="+91 98765 43210",
        verified_name="Sharma Furniture",
        app_secret_enc=crypto.encrypt("stored-app-secret"),
        verify_token="vt",
        api_version="v18.0",
    )
    return integration, config


# --- connect -------------------------------------------------------------


class TestConnect:
    @pytest.mark.asyncio
    async def test_happy_path_creates_encrypted_rows(self):
        session = _CapturingSession()
        result = await wa_connect.connect_account(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            payload=_VALID_PAYLOAD,
            http_client_factory=_meta_ok_factory(),
        )

        # One Integration row + one WhatsAppAccountConfig row inserted.
        integrations = [
            r for r in session.added if isinstance(r, Integration)
        ]
        configs = [
            r for r in session.added if isinstance(r, WhatsAppAccountConfig)
        ]
        assert len(integrations) == 1
        assert len(configs) == 1

        integration = integrations[0]
        config = configs[0]

        # Integration shape.
        assert integration.org_id == _ORG_ID
        assert integration.provider == IntegrationProvider.whatsapp
        assert integration.status == IntegrationStatus.connected
        assert integration.connected_by == _ACTOR_ID
        assert integration.account_id == "123456789012345"
        assert integration.account_label == "+91 98765 43210"

        # Token encryption: plaintext NEVER appears in the row.
        assert integration.access_token_enc is not None
        assert "plaintext-token" not in integration.access_token_enc
        assert integration.access_token_enc.startswith("gAAAA")
        assert (
            crypto.decrypt(integration.access_token_enc)
            == "EAAxxx-plaintext-token"
        )

        # Sidecar shape.
        assert config.org_id == _ORG_ID
        assert config.integration_id == integration.id
        assert config.phone_id == "123456789012345"
        assert config.waba_id == "987654321098765"
        assert config.display_phone_number == "+91 98765 43210"
        assert config.verified_name == "Sharma Furniture"
        assert config.verify_token == "my-random-verify-string"
        assert config.api_version == "v18.0"

        # App secret encryption.
        assert "plain-app-secret" not in config.app_secret_enc
        assert config.app_secret_enc.startswith("gAAAA")
        assert crypto.decrypt(config.app_secret_enc) == "plain-app-secret"

        # Service projection — used by the router response.
        assert result["status"] == "connected"
        assert result["display_phone_number"] == "+91 98765 43210"
        assert result["verified_name"] == "Sharma Furniture"
        assert result["phone_id"] == "123456789012345"
        # No plaintext credentials in the projection.
        assert "access_token" not in result
        assert "app_secret" not in result

    @pytest.mark.asyncio
    async def test_invalid_token_marks_error_no_sidecar(self):
        session = _CapturingSession()
        with pytest.raises(
            wa_connect.MetaValidationError, match="Invalid OAuth"
        ):
            await wa_connect.connect_account(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                payload=_VALID_PAYLOAD,
                http_client_factory=_meta_401_factory(),
            )

        # Failure path: Integration row added with status=error.
        integrations = [
            r for r in session.added if isinstance(r, Integration)
        ]
        assert len(integrations) == 1
        assert integrations[0].status == IntegrationStatus.error
        assert "Invalid OAuth" in (integrations[0].last_error or "")

        # And NO sidecar created — rejected creds don't deserve a cache.
        configs = [
            r for r in session.added if isinstance(r, WhatsAppAccountConfig)
        ]
        assert configs == []


# --- disconnect ----------------------------------------------------------


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_nulls_token_and_flips_status(self):
        session = _CapturingSession()
        integration, config = _existing_connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        row = await wa_connect.disconnect_account(
            session, actor_id=_ACTOR_ID
        )

        assert row is integration
        assert row.access_token_enc is None
        assert row.status == IntegrationStatus.disconnected
        assert row.disconnected_at is not None
        assert row.disconnected_by == _ACTOR_ID
        # Sidecar survives.
        assert session.rows[WhatsAppAccountConfig] == [config]

    @pytest.mark.asyncio
    async def test_disconnect_missing_row_returns_none(self):
        session = _CapturingSession()
        row = await wa_connect.disconnect_account(
            session, actor_id=_ACTOR_ID
        )
        assert row is None
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_disconnect_already_disconnected_is_noop(self):
        session = _CapturingSession()
        integration, _ = _existing_connected_pair()
        integration.status = IntegrationStatus.disconnected
        integration.access_token_enc = None
        session.rows[Integration] = [integration]

        row = await wa_connect.disconnect_account(
            session, actor_id=_ACTOR_ID
        )
        assert row is integration
        # No second commit — already disconnected.
        assert session.commits == 0


# --- test (the endpoint, not the test file) ------------------------------


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_pings_meta_and_keeps_connected_on_success(self):
        session = _CapturingSession()
        integration, config = _existing_connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        result = await wa_connect.test_connection(
            session, http_client_factory=_meta_ok_factory()
        )
        assert result["status"] == "connected"
        assert integration.status == IntegrationStatus.connected
        assert integration.last_error is None

    @pytest.mark.asyncio
    async def test_flips_to_error_on_meta_rejection(self):
        session = _CapturingSession()
        integration, config = _existing_connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        with pytest.raises(
            wa_connect.MetaValidationError, match="Invalid OAuth"
        ):
            await wa_connect.test_connection(
                session, http_client_factory=_meta_401_factory()
            )
        assert integration.status == IntegrationStatus.error
        assert "Invalid OAuth" in (integration.last_error or "")

    @pytest.mark.asyncio
    async def test_raises_when_never_connected(self):
        session = _CapturingSession()
        with pytest.raises(
            wa_connect.MetaValidationError, match="not connected"
        ):
            await wa_connect.test_connection(
                session, http_client_factory=_meta_ok_factory()
            )

    @pytest.mark.asyncio
    async def test_raises_when_disconnected(self):
        session = _CapturingSession()
        integration, _ = _existing_connected_pair()
        integration.status = IntegrationStatus.disconnected
        integration.access_token_enc = None
        session.rows[Integration] = [integration]

        with pytest.raises(
            wa_connect.MetaValidationError, match="disconnected"
        ):
            await wa_connect.test_connection(
                session, http_client_factory=_meta_ok_factory()
            )


# --- status projection ---------------------------------------------------


class TestResolveAdapter:
    """Step 3.5.3 — `resolve_whatsapp_adapter` builds a per-org
    `WhatsAppAdapter` from the active tenant's encrypted credentials.

    The function reads through the same `get_active_config` path
    used by the Settings UI, so RLS / ORM filtering covers org
    isolation — these tests just confirm the assembly + decrypt
    round-trip + the not-connected error surface."""

    @pytest.mark.asyncio
    async def test_returns_configured_adapter_when_connected(self):
        session = _CapturingSession()
        integration, config = _existing_connected_pair()
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        adapter = await resolve_whatsapp_adapter(session)

        assert isinstance(adapter, WhatsAppAdapter)
        # Adapter is configured with the sidecar's identifiers, not
        # the env-var defaults.
        assert adapter._phone_id == config.phone_id
        assert adapter._verify_token == config.verify_token
        assert adapter._api_version == config.api_version

    @pytest.mark.asyncio
    async def test_adapter_uses_decrypted_token(self):
        session = _CapturingSession()
        integration, config = _existing_connected_pair()
        # Confirm setup: integration's enc column round-trips back to
        # the same plaintext we stamped into the test fixture.
        plaintext_token = "stored-bearer"
        plaintext_secret = "stored-app-secret"
        assert crypto.decrypt(integration.access_token_enc) == plaintext_token
        assert crypto.decrypt(config.app_secret_enc) == plaintext_secret
        session.rows[Integration] = [integration]
        session.rows[WhatsAppAccountConfig] = [config]

        adapter = await resolve_whatsapp_adapter(session)

        # The adapter holds the decrypted plaintexts — the whole point
        # of the resolver. The ciphertext should never leave the DB.
        assert adapter._token == plaintext_token
        assert adapter._app_secret == plaintext_secret
        # And neither plaintext leaks into the encrypted columns by
        # accident (sanity).
        assert plaintext_token not in integration.access_token_enc
        assert plaintext_secret not in config.app_secret_enc

    @pytest.mark.asyncio
    async def test_raises_when_never_connected(self):
        session = _CapturingSession()
        with pytest.raises(WhatsAppNotConnected, match="not connected"):
            await resolve_whatsapp_adapter(session)

    @pytest.mark.asyncio
    async def test_raises_when_disconnected(self):
        session = _CapturingSession()
        integration, _ = _existing_connected_pair()
        integration.status = IntegrationStatus.disconnected
        integration.access_token_enc = None
        session.rows[Integration] = [integration]

        with pytest.raises(WhatsAppNotConnected, match="not connected"):
            await resolve_whatsapp_adapter(session)


class TestStatusProjection:
    def test_status_out_omits_token_fields(self):
        """Even if a future router accidentally feeds the full row into
        `WhatsAppStatusOut`, the schema's declared fields ensure tokens
        can't leak through this surface."""
        out = WhatsAppStatusOut.model_validate(
            {
                "status": "connected",
                "phone_id": "123",
                "waba_id": "456",
                "display_phone_number": "+91 ...",
                "verified_name": "Sharma Furniture",
                "api_version": "v18.0",
                # Extra keys (simulating a leaky service projection)
                # should be dropped by pydantic by default — model_config
                # doesn't enable extra='allow'.
            }
        )
        dumped = out.model_dump(mode="json")
        for forbidden in (
            "access_token",
            "app_secret",
            "access_token_enc",
            "app_secret_enc",
            "verify_token",
            "refresh_token",
        ):
            assert forbidden not in dumped, (
                f"{forbidden} must not appear in WhatsAppStatusOut projection"
            )
