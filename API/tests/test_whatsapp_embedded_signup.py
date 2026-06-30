"""whatsapp-platform-upgrade Step 2 — Embedded Signup orchestration tests.

Mirrors the `test_whatsapp_account_connect.py` pattern:

  - Pure-Python fake AsyncSession (no real DB).
  - Meta Graph API stubbed via an injectable httpx-client factory —
    no network, no live Meta App credentials needed.
  - Audit log silenced — we cover the audit-event names with a
    `_audit_recorder` fixture instead of asserting on DB rows.

What we prove:

  1. Happy path — code→token→WABA→phone→subscribe→register→persist
     produces an Integration row with the long-lived token encrypted,
     a sidecar with `app_secret_enc=None` (env-side now), and the
     tier cache seeded from Meta's response.
  2. Code-exchange 400 → MetaGraphError(400, "session expired"), no
     DB write, `embedded_signup.failed` audit row with reason=
     `code_exchange`.
  3. Subscribe-app 403 → MetaGraphError(403, "contact support"), no
     persist, `failed` audit with reason=`subscribe_apps`.
  4. Multi-phone WABA — the selector picks the requested phone id
     (selected_index reflects position; phones_available reflects
     total).
  5. Already-connected org — re-running ES updates the same Integration
     + sidecar rows (no duplicates), refreshes the token.
  6. Missing Meta App credentials → EmbeddedSignupNotConfigured.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from src.app.core.integrations import crypto
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp import embedded_signup as es
from src.app.core.integrations.whatsapp.meta_graph_client import (
    MetaGraphError,
)
from src.app.core.integrations.whatsapp.models import WhatsAppAccountConfig

_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- fake session --------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _CapturingSession:
    """Multi-entity fake AsyncSession. Routes select(X) to a pre-stocked
    row by inspecting `stmt.column_descriptions[0]['entity']`.

    No WHERE clause evaluation needed — production has UNIQUE
    constraints on `(org, provider)` for Integration and
    `integration_id` for the sidecar, so one row per type per test
    matches reality.
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


# --- Meta Graph API stubs ------------------------------------------------


def _stub_factory(routes: dict):
    """Build an httpx-client factory that responds based on
    (method, path_suffix) → httpx.Response. Path-suffix match keeps
    the test specs short — we don't care about the v19.0 prefix."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def request(self, method, url, params=None, data=None, headers=None):
            for (m, suffix), make_response in routes.items():
                if m == method and url.endswith(suffix):
                    if callable(make_response):
                        return make_response(params=params, data=data)
                    return make_response
            raise AssertionError(f"Unstubbed Graph call: {method} {url}")

    return lambda: _Client()


_HAPPY_TOKEN = "EAALONG_LIVED_TOKEN_xyz"
_WABA_ID = "987654321098765"
_PHONE_A_ID = "111111111111111"
_PHONE_B_ID = "222222222222222"


def _happy_routes():
    """A complete set of OK responses for the happy-path flow."""
    return {
        ("GET", "/oauth/access_token"): httpx.Response(
            200,
            json={"access_token": _HAPPY_TOKEN, "token_type": "bearer"},
        ),
        ("GET", f"/{_WABA_ID}"): httpx.Response(
            200,
            json={
                "id": _WABA_ID,
                "name": "Sharma Furniture",
                "verified_name": "Sharma Furniture",
                "timezone_offset_min": 330,
            },
        ),
        ("GET", f"/{_WABA_ID}/phone_numbers"): httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": _PHONE_A_ID,
                        "display_phone_number": "+91 98765 43210",
                        "verified_name": "Sharma Furniture",
                        "quality_rating": "GREEN",
                        "code_verification_status": "VERIFIED",
                        "messaging_limit_tier": "TIER_1K",
                    },
                ],
            },
        ),
        ("POST", f"/{_WABA_ID}/subscribed_apps"): httpx.Response(200, json={"success": True}),
        ("POST", f"/{_PHONE_A_ID}/register"): httpx.Response(200, json={"success": True}),
    }


# --- shared fixtures ------------------------------------------------------


@pytest.fixture(autouse=True)
def _platform_app_credentials(monkeypatch):
    monkeypatch.setattr(es, "META_APP_ID", "1234567890")
    monkeypatch.setattr(es, "META_APP_SECRET", "secret_xyz")
    monkeypatch.setattr(es, "WHATSAPP_GRAPH_API_VERSION", "v19.0")


@pytest.fixture
def audit_events(monkeypatch):
    """Capture `audit.log` calls instead of writing to a real DB."""
    captured: list[tuple[str, dict]] = []

    async def _capture(action, *, after=None, **_kwargs):
        captured.append((action, after or {}))

    monkeypatch.setattr(es.audit, "log", _capture)
    return captured


# --- happy path ----------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_persists_token_encrypted_and_emits_completed_audit(self, audit_events):
        session = _CapturingSession()
        result = await es.complete_embedded_signup(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            code="AQB_short_code",
            phone_number_id=_PHONE_A_ID,
            waba_id=_WABA_ID,
            http_client_factory=_stub_factory(_happy_routes()),
        )

        assert result["status"] == "connected"
        assert result["phone_id"] == _PHONE_A_ID
        assert result["waba_id"] == _WABA_ID
        assert result["display_phone_number"] == "+91 98765 43210"
        assert result["verified_name"] == "Sharma Furniture"
        assert result["phone_numbers_available"] == 1
        assert result["selected_index"] == 0
        assert result["messaging_limit_tier"] == "TIER_1K"
        assert result["quality_rating"] == "GREEN"

        integrations = [r for r in session.added if isinstance(r, Integration)]
        configs = [r for r in session.added if isinstance(r, WhatsAppAccountConfig)]
        assert len(integrations) == 1
        assert len(configs) == 1

        integration = integrations[0]
        config = configs[0]

        # Token encryption: plaintext NEVER appears in the row.
        assert integration.access_token_enc is not None
        assert _HAPPY_TOKEN not in integration.access_token_enc
        assert integration.access_token_enc.startswith("gAAAA")
        assert crypto.decrypt(integration.access_token_enc) == _HAPPY_TOKEN

        # ES path: no per-org app_secret (env-side now).
        assert config.app_secret_enc is None
        # Tier cache seeded from Meta's response.
        assert config.messaging_limit_tier == "TIER_1K"
        assert config.tier_synced_at is not None

        actions = [a for a, _ in audit_events]
        assert "integration.whatsapp.embedded_signup.code_exchanged" in actions
        assert "integration.whatsapp.embedded_signup.completed" in actions

    @pytest.mark.asyncio
    async def test_multi_phone_waba_selects_requested_phone(self, audit_events):
        session = _CapturingSession()
        routes = _happy_routes()
        # Two phones — pick the second one.
        routes[("GET", f"/{_WABA_ID}/phone_numbers")] = httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": _PHONE_A_ID,
                        "display_phone_number": "+91 98765 43210",
                        "verified_name": "Showroom A",
                        "quality_rating": "GREEN",
                        "messaging_limit_tier": "TIER_1K",
                    },
                    {
                        "id": _PHONE_B_ID,
                        "display_phone_number": "+91 91234 56789",
                        "verified_name": "Showroom B",
                        "quality_rating": "YELLOW",
                        "messaging_limit_tier": "TIER_250",
                    },
                ],
            },
        )
        routes[("POST", f"/{_PHONE_B_ID}/register")] = httpx.Response(200, json={"success": True})

        result = await es.complete_embedded_signup(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            code="AQB_short_code",
            phone_number_id=_PHONE_B_ID,
            waba_id=_WABA_ID,
            http_client_factory=_stub_factory(routes),
        )

        assert result["phone_id"] == _PHONE_B_ID
        assert result["selected_index"] == 1
        assert result["phone_numbers_available"] == 2
        assert result["quality_rating"] == "YELLOW"


# --- error paths ---------------------------------------------------------


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_code_exchange_400_maps_to_session_expired(self, audit_events):
        session = _CapturingSession()
        routes = _happy_routes()
        routes[("GET", "/oauth/access_token")] = httpx.Response(
            400,
            json={
                "error": {
                    "message": "Invalid verification code format.",
                    "code": 100,
                }
            },
        )

        with pytest.raises(MetaGraphError) as exc_info:
            await es.complete_embedded_signup(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                code="AQB_invalid",
                phone_number_id=_PHONE_A_ID,
                waba_id=_WABA_ID,
                http_client_factory=_stub_factory(routes),
            )
        assert exc_info.value.http_status == 400
        assert "session expired" in exc_info.value.user_message.lower()

        # No persist happened.
        assert all(not isinstance(r, Integration) for r in session.added)
        # `failed` audit captured with the reason.
        failed = [a for a in audit_events if a[0] == "integration.whatsapp.embedded_signup.failed"]
        assert failed, "expected a failed audit row"
        assert failed[0][1]["reason"] == "code_exchange"

    @pytest.mark.asyncio
    async def test_subscribe_403_maps_to_contact_support(self, audit_events):
        session = _CapturingSession()
        routes = _happy_routes()
        routes[("POST", f"/{_WABA_ID}/subscribed_apps")] = httpx.Response(
            403,
            json={
                "error": {
                    "message": (
                        "The user has not granted the application "
                        "the permission to perform this action."
                    ),
                    "code": 200,
                }
            },
        )

        with pytest.raises(MetaGraphError) as exc_info:
            await es.complete_embedded_signup(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                code="AQB_short_code",
                phone_number_id=_PHONE_A_ID,
                waba_id=_WABA_ID,
                http_client_factory=_stub_factory(routes),
            )
        assert exc_info.value.http_status == 403
        assert "contact support" in exc_info.value.user_message.lower()

        failed = [a for a in audit_events if a[0] == "integration.whatsapp.embedded_signup.failed"]
        assert failed and failed[0][1]["reason"] == "subscribe_apps"

    @pytest.mark.asyncio
    async def test_webhook_not_verified_maps_to_503(self, audit_events):
        session = _CapturingSession()
        routes = _happy_routes()
        routes[("POST", f"/{_WABA_ID}/subscribed_apps")] = httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        "The callback URL is not verified. "
                        "Please verify the webhook URL in your app "
                        "settings."
                    ),
                    "code": 100,
                }
            },
        )

        with pytest.raises(MetaGraphError) as exc_info:
            await es.complete_embedded_signup(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                code="AQB_short_code",
                phone_number_id=_PHONE_A_ID,
                waba_id=_WABA_ID,
                http_client_factory=_stub_factory(routes),
            )
        assert exc_info.value.http_status == 503
        assert "webhook" in exc_info.value.user_message.lower()


# --- idempotency ---------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_reconnect_updates_existing_rows_no_duplicates(self, audit_events):
        session = _CapturingSession()
        # Pre-stock an already-connected Integration + sidecar (an org
        # that hit the popup once, now coming back through it).
        existing_integration = Integration(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            provider=IntegrationProvider.whatsapp,
            account_id=_PHONE_A_ID,
            account_label="+91 98765 43210",
            access_token_enc=crypto.encrypt("OLD_TOKEN"),
            refresh_token_enc=None,
            token_expires_at=None,
            scopes=None,
            status=IntegrationStatus.connected,
            last_error=None,
            connected_at=datetime(2026, 1, 1, tzinfo=UTC),
            connected_by=_ACTOR_ID,
        )
        existing_config = WhatsAppAccountConfig(
            id=uuid.uuid4(),
            org_id=_ORG_ID,
            integration_id=existing_integration.id,
            phone_id=_PHONE_A_ID,
            waba_id=_WABA_ID,
            display_phone_number="+91 98765 43210",
            verified_name="Sharma Furniture",
            app_secret_enc=None,
            verify_token="old-verify-token",
            api_version="v19.0",
            rate_limit_per_sec=50,
            messaging_limit_tier="TIER_250",
            tier_synced_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.rows[Integration].append(existing_integration)
        session.rows[WhatsAppAccountConfig].append(existing_config)

        await es.complete_embedded_signup(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            code="AQB_short_code",
            phone_number_id=_PHONE_A_ID,
            waba_id=_WABA_ID,
            http_client_factory=_stub_factory(_happy_routes()),
        )

        # No new rows added — same row mutated in place.
        assert not any(isinstance(r, Integration) for r in session.added)
        assert not any(isinstance(r, WhatsAppAccountConfig) for r in session.added)
        # Token rotated.
        assert crypto.decrypt(existing_integration.access_token_enc) == _HAPPY_TOKEN
        # Tier refreshed.
        assert existing_config.messaging_limit_tier == "TIER_1K"


# --- configuration -------------------------------------------------------


class TestConfiguration:
    @pytest.mark.asyncio
    async def test_missing_meta_app_credentials_raises_typed_error(self, monkeypatch):
        monkeypatch.setattr(es, "META_APP_ID", "")
        monkeypatch.setattr(es, "META_APP_SECRET", "")

        session = _CapturingSession()
        with pytest.raises(es.EmbeddedSignupNotConfigured):
            await es.complete_embedded_signup(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                code="AQB_short_code",
                phone_number_id=_PHONE_A_ID,
                waba_id=_WABA_ID,
                http_client_factory=_stub_factory(_happy_routes()),
            )


# --- GET /embedded-signup/config (Step 3 backend half) --------------------


class TestEmbeddedSignupConfigEndpoint:
    """The frontend popup boots from this endpoint — see Step 3.

    No Meta calls; no DB. Just asserts the route function returns the
    env-sourced values in the documented shape and that the schema
    rejects anything else."""

    @pytest.mark.asyncio
    async def test_returns_env_values_in_documented_shape(self, monkeypatch):
        from src.app.core.integrations.whatsapp import router as wa_router

        monkeypatch.setattr(wa_router, "META_APP_ID", "1234567890")
        monkeypatch.setattr(
            wa_router,
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID",
            "config_xyz",
        )
        monkeypatch.setattr(wa_router, "WHATSAPP_GRAPH_API_VERSION", "v19.0")

        result = await wa_router.embedded_signup_config_endpoint(
            _user=object(),
        )

        assert result.app_id == "1234567890"
        assert result.config_id == "config_xyz"
        assert result.graph_api_version == "v19.0"

    @pytest.mark.asyncio
    async def test_returns_empty_strings_when_unconfigured(self, monkeypatch):
        from src.app.core.integrations.whatsapp import router as wa_router

        monkeypatch.setattr(wa_router, "META_APP_ID", "")
        monkeypatch.setattr(wa_router, "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "")
        monkeypatch.setattr(wa_router, "WHATSAPP_GRAPH_API_VERSION", "v19.0")

        result = await wa_router.embedded_signup_config_endpoint(
            _user=object(),
        )

        # Empty strings are the documented "not configured" sentinel —
        # the frontend renders an inline error when app_id is blank.
        assert result.app_id == ""
        assert result.config_id == ""
        assert result.graph_api_version == "v19.0"
