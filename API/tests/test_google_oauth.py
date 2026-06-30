"""Step 2 — Google Ads OAuth flow tests.

Five groups, all pure-unit (no DB, no live HTTP — same shape as the
embed / whatsapp tests):

  1. State signing — round-trip, tamper-evident, expiry-enforced.
  2. `start_authorize` — URL shape + scopes + offline/consent flags.
  3. `exchange_code_for_tokens` — mocked httpx, happy + error paths.
  4. `handle_callback` — end-to-end via a `_CapturingSession` stand-in
     (Service.upsert's audit.log is patched to a no-op so the unit
     test doesn't try to open a real DB connection).
  5. `GoogleAdsRestClient._get_access_token` — uses cached token when
     fresh, calls the refresh endpoint when expired, persists the
     new token + new expiry.
  6. `sync_forms.list_accessible_accounts` + `list_lead_forms` parsing.

The Google Ads REST API isn't called for real; we drive the client
with a `_FakeAsyncClient` that records calls and returns canned
responses (same approach as `test_whatsapp_send.py`).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from src.app.core.integrations import crypto, service
from src.app.core.integrations.google import api_client as gac_module
from src.app.core.integrations.google import oauth, sync_forms
from src.app.core.integrations.google.api_client import GoogleAdsRestClient
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)

# --- Shared fakes --------------------------------------------------------


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
    """Stand-in for `httpx.AsyncClient` — records calls + returns
    canned responses by URL. Same pattern as `test_whatsapp_send.py`.

    Production code creates a per-call client via
    `async with httpx.AsyncClient(...) as c`. Tests inject this
    instance directly via the `http_client` parameter on the
    OAuth helpers / `GoogleAdsRestClient`, so the `async with` path
    isn't exercised — single-shot calls are fine.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # Map (METHOD, url-prefix) → _FakeResponse. The first prefix
        # that matches the request URL wins.
        self.responses: list[tuple[str, str, _FakeResponse]] = []

    def respond(self, method: str, url_prefix: str, response: _FakeResponse) -> None:
        self.responses.append((method.upper(), url_prefix, response))

    def _lookup(self, method: str, url: str) -> _FakeResponse:
        for m, prefix, resp in self.responses:
            if m == method.upper() and url.startswith(prefix):
                return resp
        raise AssertionError(
            f"No mocked response for {method} {url}; "
            f"registered={[(m, p) for m, p, _ in self.responses]}"
        )

    async def post(
        self, url: str, *, data: Any = None, json: Any = None, headers: Any = None
    ) -> _FakeResponse:
        self.calls.append(
            {"method": "POST", "url": url, "data": data, "json": json, "headers": headers}
        )
        return self._lookup("POST", url)

    async def get(self, url: str, *, headers: Any = None) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return self._lookup("GET", url)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Any = None,
        json: Any = None,
    ) -> _FakeResponse:
        self.calls.append({"method": method.upper(), "url": url, "headers": headers, "json": json})
        return self._lookup(method, url)


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _CapturingSession:
    """Minimal AsyncSession stand-in — same shape as the Step 1 tests."""

    def __init__(self, *, existing: Integration | None = None) -> None:
        self.existing = existing
        self.added: list = []
        self.committed = False

    async def execute(self, _stmt):
        return _FakeResult(self.existing)

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        pass


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """The OAuth callback eventually calls `service.upsert(...)`, which
    fires `audit.log`. `audit.log` opens its own session — stub it out
    so unit tests don't touch the real DB."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


@pytest.fixture
def _google_oauth_env(monkeypatch):
    """Force Google OAuth env vars to non-empty values so the
    `start_authorize` 503 guard doesn't fire when running unit tests
    against an empty .env."""
    monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        oauth,
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/v1/integrations/google/callback",
    )
    monkeypatch.setattr(gac_module, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(gac_module, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(gac_module, "GOOGLE_ADS_DEVELOPER_TOKEN", "test-dev-token")
    monkeypatch.setattr(gac_module, "GOOGLE_ADS_API_VERSION", "v17")


_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- 1. State signing ---------------------------------------------------


class TestStateSigning:
    def test_roundtrip_recovers_payload(self):
        signed = oauth._sign_state(
            {
                "org_id": str(_ORG_ID),
                "actor_id": str(_ACTOR_ID),
                "nonce": "n",
                "exp": int(time.time()) + 600,
            }
        )
        decoded = oauth.verify_state(signed)
        assert decoded["org_id"] == str(_ORG_ID)
        assert decoded["actor_id"] == str(_ACTOR_ID)

    def test_tampered_signature_raises(self):
        signed = oauth._sign_state(
            {"org_id": str(_ORG_ID), "actor_id": None, "nonce": "x", "exp": int(time.time()) + 600}
        )
        body, sig = signed.split(".", 1)
        # Flip a char near the START of the signature — the LAST char
        # of a base64url-encoded 32-byte digest only contributes 4 of
        # its 6 bits to the decoded bytes, so flipping it doesn't
        # always change the digest (flaky). The first char always
        # does.
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        with pytest.raises(Exception) as exc:
            oauth.verify_state(f"{body}.{flipped}")
        assert "signature" in str(exc.value.detail).lower()

    def test_expired_state_raises(self):
        signed = oauth._sign_state(
            {"org_id": str(_ORG_ID), "actor_id": None, "nonce": "x", "exp": int(time.time()) - 1}
        )
        with pytest.raises(Exception) as exc:
            oauth.verify_state(signed)
        assert "expired" in str(exc.value.detail).lower()

    def test_malformed_state_raises(self):
        with pytest.raises(Exception):
            oauth.verify_state("not-a-state")
        with pytest.raises(Exception):
            oauth.verify_state("")


# --- 2. start_authorize URL shape ---------------------------------------


class TestStartAuthorize:
    def test_returns_google_consent_url(self, _google_oauth_env):
        url = oauth.start_authorize(org_id=_ORG_ID, actor_id=_ACTOR_ID)
        parsed = urlparse(url)
        assert parsed.netloc == "accounts.google.com"
        assert parsed.path == "/o/oauth2/v2/auth"

        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["test-client-id"]
        assert qs["response_type"] == ["code"]
        # offline + consent are both required for refresh_token issuance.
        assert qs["access_type"] == ["offline"]
        assert qs["prompt"] == ["consent"]
        # adwords + email + openid scopes all present.
        scope_str = qs["scope"][0]
        assert "https://www.googleapis.com/auth/adwords" in scope_str
        assert "https://www.googleapis.com/auth/userinfo.email" in scope_str
        assert "openid" in scope_str
        # State is signed and decodable.
        state = qs["state"][0]
        payload = oauth.verify_state(state)
        assert payload["org_id"] == str(_ORG_ID)
        assert payload["actor_id"] == str(_ACTOR_ID)
        assert payload["exp"] > int(time.time())

    def test_503_when_client_id_missing(self, monkeypatch):
        monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_ID", "")
        with pytest.raises(Exception) as exc:
            oauth.start_authorize(org_id=_ORG_ID, actor_id=_ACTOR_ID)
        assert exc.value.status_code == 503


# --- 3. exchange_code_for_tokens ----------------------------------------


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_happy_path_returns_tokens(self, _google_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {
                    "access_token": "ya29.abc",
                    "refresh_token": "1//refresh",
                    "expires_in": 3600,
                    "scope": "openid",
                    "token_type": "Bearer",
                },
            ),
        )

        tokens = await oauth.exchange_code_for_tokens(code="auth-code-123", http_client=client)

        assert tokens.access_token == "ya29.abc"
        assert tokens.refresh_token == "1//refresh"
        assert tokens.expires_at > int(time.time())
        # The call shape — form-encoded `data=`, not JSON.
        call = client.calls[0]
        assert call["url"] == "https://oauth2.googleapis.com/token"
        assert call["data"]["code"] == "auth-code-123"
        assert call["data"]["grant_type"] == "authorization_code"
        assert call["data"]["client_id"] == "test-client-id"
        assert call["data"]["client_secret"] == "test-secret"

    @pytest.mark.asyncio
    async def test_non_200_raises_400(self, _google_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(400, {"error": "invalid_grant", "error_description": "Bad code"}),
        )
        with pytest.raises(Exception) as exc:
            await oauth.exchange_code_for_tokens(code="bad", http_client=client)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_access_token_raises_502(self, _google_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(200, {"refresh_token": "only-refresh"}),
        )
        with pytest.raises(Exception) as exc:
            await oauth.exchange_code_for_tokens(code="x", http_client=client)
        assert exc.value.status_code == 502


# --- 4. handle_callback end-to-end --------------------------------------


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_happy_path_upserts_encrypted_tokens(self, _google_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {
                    "access_token": "fresh-access",
                    "refresh_token": "fresh-refresh",
                    "expires_in": 3600,
                },
            ),
        )
        client.respond(
            "GET",
            "https://www.googleapis.com/oauth2/v2/userinfo",
            _FakeResponse(200, {"email": "asha@example.com"}),
        )
        state = oauth._sign_state(
            {
                "org_id": str(_ORG_ID),
                "actor_id": str(_ACTOR_ID),
                "nonce": "n",
                "exp": int(time.time()) + 600,
            }
        )
        session = _CapturingSession(existing=None)

        integration = await oauth.handle_callback(
            session,
            code="auth-code-xyz",
            state=state,
            http_client=client,
        )

        assert integration.org_id == _ORG_ID
        assert integration.provider == IntegrationProvider.google_ads
        assert integration.status == IntegrationStatus.connected
        assert integration.account_label == "asha@example.com"
        assert integration.access_token_enc is not None
        # Plaintext NEVER appears in the persisted ciphertext.
        assert "fresh-access" not in integration.access_token_enc
        # decrypt round-trips back to the plaintext.
        access, refresh = service.decrypt_tokens(integration)
        assert access == "fresh-access"
        assert refresh == "fresh-refresh"
        # Scopes captured.
        assert "https://www.googleapis.com/auth/adwords" in integration.scopes

    @pytest.mark.asyncio
    async def test_callback_with_expired_state_raises(self, _google_oauth_env):
        client = _FakeAsyncClient()
        expired_state = oauth._sign_state(
            {
                "org_id": str(_ORG_ID),
                "actor_id": None,
                "nonce": "n",
                "exp": int(time.time()) - 1,
            }
        )
        session = _CapturingSession(existing=None)
        with pytest.raises(Exception) as exc:
            await oauth.handle_callback(
                session,
                code="anything",
                state=expired_state,
                http_client=client,
            )
        assert exc.value.status_code == 400
        # No HTTP call should have been made — we abort on state check.
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_callback_userinfo_failure_still_persists(self, _google_oauth_env):
        """Userinfo is best-effort. If Google's userinfo endpoint
        returns a 500, we still complete the connect — `account_label`
        just stays None."""
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {
                    "access_token": "a",
                    "refresh_token": "r",
                    "expires_in": 3600,
                },
            ),
        )
        client.respond(
            "GET",
            "https://www.googleapis.com/oauth2/v2/userinfo",
            _FakeResponse(500, {"error": "internal"}),
        )
        state = oauth._sign_state(
            {
                "org_id": str(_ORG_ID),
                "actor_id": None,
                "nonce": "n",
                "exp": int(time.time()) + 600,
            }
        )
        session = _CapturingSession(existing=None)
        integration = await oauth.handle_callback(
            session, code="x", state=state, http_client=client
        )
        assert integration.account_label is None
        assert integration.status == IntegrationStatus.connected


# --- 5. GoogleAdsRestClient token refresh -------------------------------


def _connected_integration(
    *,
    access: str = "live-access",
    refresh: str | None = "live-refresh",
    expires_at: datetime | None = None,
) -> Integration:
    return Integration(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        provider=IntegrationProvider.google_ads,
        account_id="1234567890",
        account_label="asha@example.com",
        access_token_enc=crypto.encrypt(access),
        refresh_token_enc=(crypto.encrypt(refresh) if refresh is not None else None),
        token_expires_at=expires_at,
        scopes=["https://www.googleapis.com/auth/adwords"],
        status=IntegrationStatus.connected,
    )


class TestApiClientRefresh:
    @pytest.mark.asyncio
    async def test_uses_cached_token_when_fresh(self, _google_oauth_env):
        fresh = datetime.now(UTC) + timedelta(minutes=30)
        row = _connected_integration(expires_at=fresh)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://googleads.googleapis.com/v17/customers:listAccessibleCustomers",
            _FakeResponse(200, {"resourceNames": ["customers/1234567890"]}),
        )

        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)
        body = await rest.get("customers:listAccessibleCustomers")
        assert "resourceNames" in body
        # No refresh HTTP call — token still good.
        assert all("oauth2.googleapis.com/token" not in c["url"] for c in client.calls)

    @pytest.mark.asyncio
    async def test_refreshes_expired_token_and_persists(self, _google_oauth_env):
        stale = datetime.now(UTC) - timedelta(minutes=5)
        row = _connected_integration(expires_at=stale)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        # Refresh response — new access token, expires in 1h.
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {
                    "access_token": "rotated-access",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            ),
        )
        # The API call that triggered the refresh — list accounts.
        client.respond(
            "GET",
            "https://googleads.googleapis.com/v17/customers:listAccessibleCustomers",
            _FakeResponse(200, {"resourceNames": []}),
        )

        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)
        await rest.get("customers:listAccessibleCustomers")

        # Refresh fired with form-encoded data.
        refresh_calls = [c for c in client.calls if "oauth2.googleapis.com/token" in c["url"]]
        assert len(refresh_calls) == 1
        assert refresh_calls[0]["data"]["grant_type"] == "refresh_token"
        assert refresh_calls[0]["data"]["client_id"] == "test-client-id"

        # Row updated in place: new ciphertext + new expiry + commit.
        assert session.committed is True
        assert "rotated-access" not in (row.access_token_enc or "")
        assert crypto.decrypt(row.access_token_enc) == "rotated-access"
        # New expiry roughly 1h in the future (allow slack).
        assert row.token_expires_at is not None
        delta = (row.token_expires_at - datetime.now(UTC)).total_seconds()
        assert 3500 < delta < 3700

    @pytest.mark.asyncio
    async def test_refresh_failure_flips_to_expired(self, _google_oauth_env):
        stale = datetime.now(UTC) - timedelta(minutes=5)
        row = _connected_integration(expires_at=stale)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(401, {"error": "invalid_grant"}),
        )

        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)
        with pytest.raises(Exception) as exc:
            await rest.get("customers:listAccessibleCustomers")
        assert exc.value.status_code == 401
        assert row.status == IntegrationStatus.expired
        assert "refresh failed" in (row.last_error or "")

    @pytest.mark.asyncio
    async def test_503_when_developer_token_missing(self, monkeypatch):
        monkeypatch.setattr(gac_module, "GOOGLE_ADS_DEVELOPER_TOKEN", "")
        row = _connected_integration(expires_at=datetime.now(UTC) + timedelta(hours=1))
        session = _CapturingSession(existing=row)
        with pytest.raises(Exception) as exc:
            GoogleAdsRestClient(
                integration=row,
                session=session,
                http_client=_FakeAsyncClient(),
            )
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_409_when_integration_disconnected(self, _google_oauth_env):
        row = _connected_integration(expires_at=datetime.now(UTC) + timedelta(hours=1))
        row.status = IntegrationStatus.disconnected
        session = _CapturingSession(existing=row)
        with pytest.raises(Exception) as exc:
            GoogleAdsRestClient(
                integration=row,
                session=session,
                http_client=_FakeAsyncClient(),
            )
        assert exc.value.status_code == 409


# --- 6. sync_forms parsing ----------------------------------------------


class TestSyncForms:
    @pytest.mark.asyncio
    async def test_list_accessible_accounts(self, _google_oauth_env):
        fresh = datetime.now(UTC) + timedelta(hours=1)
        row = _connected_integration(expires_at=fresh)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://googleads.googleapis.com/v17/customers:listAccessibleCustomers",
            _FakeResponse(
                200,
                {
                    "resourceNames": [
                        "customers/1234567890",
                        "customers/9876543210",
                    ]
                },
            ),
        )
        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)

        accounts = await sync_forms.list_accessible_accounts(rest)
        assert [a.customer_id for a in accounts] == [
            "1234567890",
            "9876543210",
        ]
        assert accounts[0].resource_name == "customers/1234567890"

    @pytest.mark.asyncio
    async def test_list_lead_forms_parses_search_stream(self, _google_oauth_env):
        fresh = datetime.now(UTC) + timedelta(hours=1)
        row = _connected_integration(expires_at=fresh)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://googleads.googleapis.com/v17/customers/1234567890/googleAds:searchStream",
            _FakeResponse(
                200,
                [
                    {
                        "results": [
                            {
                                "asset": {
                                    "id": "11111",
                                    "name": "Showroom Visit Form",
                                    "resourceName": ("customers/1234567890/assets/11111"),
                                }
                            },
                            {
                                "asset": {
                                    "id": "22222",
                                    "name": "Bulk Order Inquiry",
                                    "resourceName": ("customers/1234567890/assets/22222"),
                                }
                            },
                        ]
                    }
                ],
            ),
        )
        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)

        forms = await sync_forms.list_lead_forms(rest, customer_id="1234567890")
        assert [f.form_id for f in forms] == ["11111", "22222"]
        assert forms[0].name == "Showroom Visit Form"

    @pytest.mark.asyncio
    async def test_list_lead_forms_empty_when_no_results(self, _google_oauth_env):
        fresh = datetime.now(UTC) + timedelta(hours=1)
        row = _connected_integration(expires_at=fresh)
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://googleads.googleapis.com/v17/customers/1234567890/googleAds:searchStream",
            _FakeResponse(200, {"results": []}),
        )
        rest = GoogleAdsRestClient(integration=row, session=session, http_client=client)
        forms = await sync_forms.list_lead_forms(rest, customer_id="1234567890")
        assert forms == []
