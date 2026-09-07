"""Step 4 — Meta (Facebook + Instagram) Ads OAuth + subscription tests.

Same approach as Step 1 / Step 2 / Step 3 — pure-unit with monkey-
patched DB sessions and a `_FakeAsyncClient` stand-in for httpx
(no `respx` dep needed, matches `test_whatsapp_send.py` /
`test_google_oauth.py` patterns).

Seven groups:

  1. State signing — roundtrip, tampered-signature, expiry, cross-provider
     (a Google-tagged state must not authenticate against the Meta callback).
  2. `start_authorize` URL shape — domain, scope set, redirect, state.
  3. `exchange_code_for_short_token` — happy + error paths.
  4. `exchange_for_long_lived_token` — happy + expires_in fallback.
  5. `handle_callback` — full flow via captured sessions; row persisted
     with `provider=meta_ads`, encrypted token, 60-day expiry.
  6. `subscriptions.list_pages / list_lead_forms / subscribe / unsubscribe`
     — parses Meta's `data:[...]` envelopes and uses the right tokens.
  7. `MetaGraphClient` — 401 OAuthException flips status to `expired`
     and raises `MetaTokenExpiredError`. `connected`-status guard at init.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from src.app.core.integrations import crypto, service
from src.app.core.integrations.meta import (
    api_client as gac_module,
)
from src.app.core.integrations.meta import (
    oauth,
    subscriptions,
)
from src.app.core.integrations.meta.api_client import (
    MetaGraphClient,
    MetaTokenExpiredError,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)

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
    """Same stand-in as `test_google_oauth.py` — keyed by
    (method, url-prefix). Tests register responses with `respond(...)`
    and assert on `.calls`."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
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

    async def get(self, url: str, *, params: Any = None, headers: Any = None) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers})
        return self._lookup("GET", url)

    async def post(
        self,
        url: str,
        *,
        params: Any = None,
        data: Any = None,
        json: Any = None,
        headers: Any = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "params": params,
                "data": data,
                "json": json,
                "headers": headers,
            }
        )
        return self._lookup("POST", url)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        json: Any = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": method.upper(),
                "url": url,
                "params": params,
                "headers": headers,
                "json": json,
            }
        )
        return self._lookup(method, url)


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _CapturingSession:
    """Minimal AsyncSession stand-in — same shape as the Step 1/2/3 tests."""

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
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service.audit, "log", _noop)


@pytest.fixture
def _meta_oauth_env(monkeypatch):
    """Force Meta OAuth env vars to non-empty values so the
    `start_authorize` 503 guard doesn't fire when running tests
    against an empty .env."""
    monkeypatch.setattr(oauth, "META_APP_ID", "test-app-id")
    monkeypatch.setattr(oauth, "META_APP_SECRET", "test-secret")
    monkeypatch.setattr(
        oauth,
        "META_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/v1/integrations/meta/callback",
    )
    monkeypatch.setattr(oauth, "META_GRAPH_API_VERSION", "v19.0")
    monkeypatch.setattr(gac_module, "META_GRAPH_API_VERSION", "v19.0")


_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- 1. State signing ---------------------------------------------------


class TestStateSigning:
    def test_roundtrip_recovers_payload(self):
        signed = oauth._sign_state(
            {
                "provider": "meta",
                "org_id": str(_ORG_ID),
                "actor_id": str(_ACTOR_ID),
                "nonce": "n",
                "exp": int(time.time()) + 600,
            }
        )
        decoded = oauth.verify_state(signed)
        assert decoded["org_id"] == str(_ORG_ID)
        assert decoded["actor_id"] == str(_ACTOR_ID)
        assert decoded["provider"] == "meta"

    def test_tampered_signature_raises(self):
        signed = oauth._sign_state(
            {
                "provider": "meta",
                "org_id": str(_ORG_ID),
                "actor_id": None,
                "nonce": "x",
                "exp": int(time.time()) + 600,
            }
        )
        body, sig = signed.split(".", 1)
        # Flip the FIRST char of the signature — the last char of a
        # base64url-encoded 32-byte digest only contributes 4 of its
        # 6 bits to the decoded bytes, so flipping it doesn't always
        # change the underlying digest. The first char always does.
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        with pytest.raises(Exception) as exc:
            oauth.verify_state(f"{body}.{flipped}")
        assert "signature" in str(exc.value.detail).lower()

    def test_expired_state_raises(self):
        signed = oauth._sign_state(
            {
                "provider": "meta",
                "org_id": str(_ORG_ID),
                "actor_id": None,
                "nonce": "x",
                "exp": int(time.time()) - 1,
            }
        )
        with pytest.raises(Exception) as exc:
            oauth.verify_state(signed)
        assert "expired" in str(exc.value.detail).lower()

    def test_cross_provider_state_rejected(self):
        """A Google-signed state (provider='google_ads' or no tag)
        must not authenticate the Meta callback even though both
        providers share the HMAC secret."""
        signed = oauth._sign_state(
            {
                "provider": "google_ads",
                "org_id": str(_ORG_ID),
                "actor_id": None,
                "nonce": "x",
                "exp": int(time.time()) + 600,
            }
        )
        with pytest.raises(Exception) as exc:
            oauth.verify_state(signed)
        assert "provider" in str(exc.value.detail).lower()

    def test_malformed_state_raises(self):
        with pytest.raises(HTTPException):
            oauth.verify_state("not-a-state")
        with pytest.raises(HTTPException):
            oauth.verify_state("")


# --- 2. start_authorize URL shape ---------------------------------------


class TestStartAuthorize:
    def test_returns_facebook_consent_url(self, _meta_oauth_env):
        url = oauth.start_authorize(org_id=_ORG_ID, actor_id=_ACTOR_ID)
        parsed = urlparse(url)
        assert parsed.netloc == "www.facebook.com"
        assert "/dialog/oauth" in parsed.path
        assert "v19.0" in parsed.path

        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["test-app-id"]
        assert qs["response_type"] == ["code"]
        # Five scopes joined by comma (Meta convention, NOT space).
        scope = qs["scope"][0]
        for required in (
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_metadata",
            "leads_retrieval",
            "business_management",
        ):
            assert required in scope
        # State decodes back to original org/actor + correct provider tag.
        payload = oauth.verify_state(qs["state"][0])
        assert payload["org_id"] == str(_ORG_ID)
        assert payload["provider"] == "meta"

    def test_503_when_app_id_missing(self, monkeypatch):
        monkeypatch.setattr(oauth, "META_APP_ID", "")
        with pytest.raises(Exception) as exc:
            oauth.start_authorize(org_id=_ORG_ID, actor_id=_ACTOR_ID)
        assert exc.value.status_code == 503


# --- 3. exchange_code_for_short_token -----------------------------------


class TestExchangeShortToken:
    @pytest.mark.asyncio
    async def test_happy_path(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(
                200,
                {"access_token": "short-abc", "token_type": "bearer", "expires_in": 3600},
            ),
        )

        token = await oauth.exchange_code_for_short_token("auth-code-123", http_client=client)
        assert token == "short-abc"
        # The call shape: GET with params, not POST.
        assert client.calls[0]["method"] == "GET"
        assert client.calls[0]["params"]["code"] == "auth-code-123"
        assert client.calls[0]["params"]["client_id"] == "test-app-id"

    @pytest.mark.asyncio
    async def test_meta_error_response_raises_400(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(
                400,
                {"error": {"message": "Bad code", "type": "OAuthException", "code": 100}},
            ),
        )
        with pytest.raises(Exception) as exc:
            await oauth.exchange_code_for_short_token("bad", http_client=client)
        assert exc.value.status_code == 400


# --- 4. exchange_for_long_lived_token -----------------------------------


class TestExchangeLongLived:
    @pytest.mark.asyncio
    async def test_happy_path_60_day_expiry(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(
                200,
                {"access_token": "long-xyz", "expires_in": 5184000},
            ),
        )

        tokens = await oauth.exchange_for_long_lived_token("short-abc", http_client=client)
        assert tokens.access_token == "long-xyz"
        # ~60 days in the future, allow generous slack.
        delta = tokens.expires_at - int(time.time())
        assert 5000000 < delta < 5300000
        # Was a fb_exchange_token grant.
        assert client.calls[0]["params"]["grant_type"] == "fb_exchange_token"
        assert client.calls[0]["params"]["fb_exchange_token"] == "short-abc"

    @pytest.mark.asyncio
    async def test_falls_back_to_60_days_when_expires_in_missing(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(200, {"access_token": "long-xyz"}),
        )
        tokens = await oauth.exchange_for_long_lived_token("short-abc", http_client=client)
        delta = tokens.expires_at - int(time.time())
        # Default = 60 days.
        assert 5100000 < delta < 5200000


# --- 5. handle_callback full flow ---------------------------------------


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_happy_path_upserts_encrypted_token(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        # Both token-endpoint legs hit the same URL — _FakeAsyncClient
        # returns the same canned response for both. We use a richer
        # one with `access_token` set to a leg-specific value.
        # Order: short-token request first, long-token second. The
        # fake returns the registered response on every match — to
        # distinguish, we just verify the LONG-LIVED value ends up
        # in the integration row.
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(
                200,
                {"access_token": "long-token", "expires_in": 5184000},
            ),
        )
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me",
            _FakeResponse(200, {"id": "fb-user-1", "name": "Asha", "email": "asha@example.com"}),
        )

        state = oauth._sign_state(
            {
                "provider": "meta",
                "org_id": str(_ORG_ID),
                "actor_id": str(_ACTOR_ID),
                "nonce": "n",
                "exp": int(time.time()) + 600,
            }
        )
        session = _CapturingSession(existing=None)

        integration = await oauth.handle_callback(
            session, code="auth-code", state=state, http_client=client
        )

        assert integration.org_id == _ORG_ID
        assert integration.provider == IntegrationProvider.meta_ads
        assert integration.status == IntegrationStatus.connected
        # Prefer email in the label when granted.
        assert integration.account_label == "asha@example.com"
        # Plaintext NEVER ends up as the ciphertext.
        assert "long-token" not in (integration.access_token_enc or "")
        access, refresh = service.decrypt_tokens(integration)
        assert access == "long-token"
        # Meta has no refresh tokens.
        assert refresh is None
        # All five scopes captured.
        for required in (
            "pages_show_list",
            "leads_retrieval",
            "business_management",
        ):
            assert required in integration.scopes

    @pytest.mark.asyncio
    async def test_callback_with_expired_state_raises(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        expired_state = oauth._sign_state(
            {
                "provider": "meta",
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
        # No HTTP call should have been made.
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_callback_userinfo_failure_still_persists(self, _meta_oauth_env):
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/oauth/access_token",
            _FakeResponse(200, {"access_token": "long-token", "expires_in": 5184000}),
        )
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me",
            _FakeResponse(500, {"error": "internal"}),
        )
        state = oauth._sign_state(
            {
                "provider": "meta",
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


# --- 6. subscriptions helpers -------------------------------------------


def _connected_meta(*, access: str = "long-user-token") -> Integration:
    return Integration(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        provider=IntegrationProvider.meta_ads,
        account_label="asha@example.com",
        access_token_enc=crypto.encrypt(access),
        refresh_token_enc=None,
        token_expires_at=datetime.now(UTC) + timedelta(days=60),
        scopes=["pages_show_list", "leads_retrieval"],
        status=IntegrationStatus.connected,
    )


class TestSubscriptions:
    @pytest.mark.asyncio
    async def test_list_pages_parses_data_envelope(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": "page-1",
                            "name": "Mumbai Showroom",
                            "access_token": "page-tok-1",
                            "category": "Furniture Store",
                        },
                        {
                            "id": "page-2",
                            "name": "Delhi Showroom",
                            "access_token": "page-tok-2",
                            "category": "Furniture Store",
                        },
                    ]
                },
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        pages = await subscriptions.list_pages(graph)
        assert [p.page_id for p in pages] == ["page-1", "page-2"]
        assert pages[0].name == "Mumbai Showroom"
        assert pages[0].access_token == "page-tok-1"
        assert pages[0].category == "Furniture Store"

    @pytest.mark.asyncio
    async def test_list_pages_skips_malformed_entries(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                200,
                {
                    "data": [
                        {"id": "p-1", "name": "Good", "access_token": "tok"},
                        # Missing access_token — should be dropped, not crash.
                        {"id": "p-2", "name": "No Token"},
                        # Missing name — dropped.
                        {"id": "p-3", "access_token": "tok"},
                        # Not a dict — dropped.
                        "not-a-page",
                    ]
                },
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        pages = await subscriptions.list_pages(graph)
        assert [p.page_id for p in pages] == ["p-1"]

    @pytest.mark.asyncio
    async def test_list_lead_forms_uses_page_token(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/page-1/leadgen_forms",
            _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": "form-1",
                            "name": "Showroom Visit",
                            "status": "ACTIVE",
                            "questions": [
                                {"key": "full_name"},
                                {"key": "email"},
                                {"key": "phone_number"},
                                {"key": "what_service_are_you_interested_in"},
                            ],
                        },
                        {
                            "id": "form-2",
                            "name": "Bulk Inquiry",
                            "status": "ACTIVE",
                            "questions": [{"key": "full_name"}],
                        },
                        {"id": "form-3", "name": "Old Form", "status": "ARCHIVED"},
                    ]
                },
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        forms = await subscriptions.list_lead_forms_for_page(
            graph, page_id="page-1", page_token="page-tok-1"
        )
        assert [f.form_id for f in forms] == ["form-1", "form-2", "form-3"]
        # Questions were extracted per form (the mapping editor's left-hand column).
        assert forms[0].questions == (
            "full_name",
            "email",
            "phone_number",
            "what_service_are_you_interested_in",
        )
        assert forms[1].questions == ("full_name",)
        # Missing `questions` field → empty tuple, never crashes.
        assert forms[2].questions == ()
        # The call carried the PAGE token, not the user token.
        call = client.calls[0]
        assert call["params"]["access_token"] == "page-tok-1"
        # And requested the `questions{key}` field expansion — that's the whole
        # point of this step (mapping editor needs the actual question keys).
        assert "questions{key}" in call["params"]["fields"]

    @pytest.mark.asyncio
    async def test_list_lead_forms_survives_malformed_questions(self, _meta_oauth_env):
        """Meta's Graph API occasionally returns half-shaped entries when a
        form is in a strange state (partial delete, permission edge case).
        Every non-dict question entry and every entry missing `key` should be
        skipped silently — the caller gets whatever keys ARE valid."""
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/page-1/leadgen_forms",
            _FakeResponse(
                200,
                {
                    "data": [
                        {
                            "id": "form-x",
                            "name": "Broken",
                            "status": "ACTIVE",
                            "questions": [
                                {"key": "email"},
                                "not-a-dict",  # skipped
                                {"label": "No key here"},  # skipped
                                {"key": "phone_number"},
                                {"key": None},  # skipped (falsy)
                            ],
                        },
                    ]
                },
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        forms = await subscriptions.list_lead_forms_for_page(
            graph, page_id="page-1", page_token="page-tok-1"
        )
        assert forms[0].questions == ("email", "phone_number")

    @pytest.mark.asyncio
    async def test_subscribe_page(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://graph.facebook.com/v19.0/page-1/subscribed_apps",
            _FakeResponse(200, {"success": True}),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        ok = await subscriptions.subscribe_page(graph, page_id="page-1", page_token="page-tok-1")
        assert ok is True
        call = client.calls[0]
        assert call["method"] == "POST"
        # `subscribed_fields=leadgen` is the whole point.
        assert call["params"]["subscribed_fields"] == "leadgen"
        # Used the page token, not user token.
        assert call["params"]["access_token"] == "page-tok-1"

    @pytest.mark.asyncio
    async def test_unsubscribe_page(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "DELETE",
            "https://graph.facebook.com/v19.0/page-1/subscribed_apps",
            _FakeResponse(200, {"success": True}),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        ok = await subscriptions.unsubscribe_page(graph, page_id="page-1", page_token="page-tok-1")
        assert ok is True
        assert client.calls[0]["method"] == "DELETE"

    @pytest.mark.asyncio
    async def test_find_page_token(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                200,
                {
                    "data": [
                        {"id": "p-1", "name": "A", "access_token": "tok-A"},
                        {"id": "p-2", "name": "B", "access_token": "tok-B"},
                    ]
                },
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        assert await subscriptions.find_page_token(graph, page_id="p-2") == "tok-B"
        # Unknown page → None.
        assert await subscriptions.find_page_token(graph, page_id="p-99") is None


# --- 7. Graph client: expired-token detection ---------------------------


class TestExpiredTokenDetection:
    @pytest.mark.asyncio
    async def test_401_flips_status_and_raises(self, _meta_oauth_env):
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                401,
                {"error": {"type": "OAuthException", "code": 190, "message": "Token expired"}},
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        with pytest.raises(MetaTokenExpiredError):
            await subscriptions.list_pages(graph)
        assert row.status == IntegrationStatus.expired
        assert "401" in (row.last_error or "")
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_400_with_oauth_exception_also_flips_status(self, _meta_oauth_env):
        """Meta sometimes returns 400 (not 401) for revoked tokens.
        The OAuthException sub-code is what we check."""
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                400,
                {"error": {"type": "OAuthException", "code": 190, "message": "Revoked"}},
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        with pytest.raises(MetaTokenExpiredError):
            await subscriptions.list_pages(graph)
        assert row.status == IntegrationStatus.expired

    @pytest.mark.asyncio
    async def test_400_non_oauth_does_not_flip_status(self, _meta_oauth_env):
        """Validation errors (bad params, bad ids) should NOT mark
        the integration `expired` — they aren't token-related."""
        row = _connected_meta()
        session = _CapturingSession(existing=row)
        client = _FakeAsyncClient()
        client.respond(
            "GET",
            "https://graph.facebook.com/v19.0/me/accounts",
            _FakeResponse(
                400,
                {"error": {"type": "GraphMethodException", "code": 100, "message": "Bad request"}},
            ),
        )
        graph = MetaGraphClient(integration=row, session=session, http_client=client)
        with pytest.raises(Exception) as exc:
            await subscriptions.list_pages(graph)
        # Bubbles up as 502, not MetaTokenExpiredError.
        assert exc.value.status_code == 502
        # Integration row UNCHANGED.
        assert row.status == IntegrationStatus.connected

    @pytest.mark.asyncio
    async def test_409_when_integration_not_connected(self, _meta_oauth_env):
        row = _connected_meta()
        row.status = IntegrationStatus.disconnected
        session = _CapturingSession(existing=row)
        with pytest.raises(Exception) as exc:
            MetaGraphClient(integration=row, session=session, http_client=_FakeAsyncClient())
        assert exc.value.status_code == 409
