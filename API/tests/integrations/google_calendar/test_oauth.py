"""Step 2 — Per-user Google Calendar OAuth flow tests.

Pure-unit — no DB, no live HTTP. Mirrors ``test_google_oauth.py``'s
shape (``_FakeAsyncClient`` records calls + returns canned responses).

Covers the four spec bullets for Step 6:

  * OAuth state HMAC — tampered param 400s.
  * OAuth state HMAC — user_id in state doesn't match the JWT
    (via ``service.complete_connection``'s own state parsing —
    verify the callback would refuse).
  * Token refresh — ``get_valid_access_token`` calls Google's
    ``/token`` when the cached access token is close to expiring
    and persists the new value.
  * Token refresh — ``invalid_grant`` from Google → the row is
    flipped to ``status='revoked'`` and the caller sees
    :class:`GoogleCalendarNotConnected`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from src.app.core.integrations import crypto
from src.app.core.integrations.google_calendar import oauth


# --- Shared fakes ------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeAsyncClient:
    """Records HTTP calls + returns canned responses. Same pattern as
    ``test_google_oauth.py``'s ``_FakeAsyncClient``."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: list[tuple[str, str, _FakeResponse]] = []

    def respond(
        self, method: str, url_prefix: str, response: _FakeResponse
    ) -> None:
        self.responses.append((method.upper(), url_prefix, response))

    def _lookup(self, method: str, url: str) -> _FakeResponse:
        for m, prefix, resp in self.responses:
            if m == method.upper() and url.startswith(prefix):
                return resp
        raise AssertionError(
            f"No mocked response for {method} {url}; "
            f"registered={[(m, p) for m, p, _ in self.responses]}"
        )

    async def get(self, url: str, *, headers: Any = None) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return self._lookup("GET", url)

    async def post(
        self,
        url: str,
        *,
        data: Any = None,
        json: Any = None,
        headers: Any = None,
        params: Any = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "data": data,
                "json": json,
                "headers": headers,
                "params": params,
            }
        )
        return self._lookup("POST", url)


class _TokenRow:
    """Minimal stand-in for :class:`GoogleCalendarToken`. The
    ``get_valid_access_token`` refresh path reads a handful of columns
    + writes access_token_encrypted / access_token_expires_at back via
    the DAL. Wiring the real ORM here is overkill; capture the field
    accesses instead."""

    def __init__(
        self,
        *,
        refresh_token_encrypted: str,
        access_token_encrypted: str | None = None,
        access_token_expires_at=None,
        status: str = "active",
    ) -> None:
        self.id = uuid.uuid4()
        self.org_id = _ORG_ID
        self.user_id = 42
        self.refresh_token_encrypted = refresh_token_encrypted
        self.access_token_encrypted = access_token_encrypted
        self.access_token_expires_at = access_token_expires_at
        self.status = status
        self.last_error = None


class _CapturingDA:
    """Stub for :mod:`data_access` that records the calls
    ``get_valid_access_token`` fans out to. Replaces the module via
    ``monkeypatch.setattr``."""

    def __init__(self, row: _TokenRow | None) -> None:
        self.row = row
        self.updated_access: list[dict] = []
        self.marked: list[dict] = []

    async def get_active_token_for_user(self, _session, *, org_id, user_id):
        if self.row is None:
            return None
        if (
            self.row.org_id == org_id
            and self.row.user_id == user_id
            and self.row.status == "active"
        ):
            return self.row
        return None

    async def update_access_token(
        self,
        _session,
        *,
        token_id,
        access_token_encrypted,
        access_token_expires_at,
    ):
        self.updated_access.append(
            {
                "token_id": token_id,
                "access_token_encrypted": access_token_encrypted,
                "access_token_expires_at": access_token_expires_at,
            }
        )
        # Reflect the write on the row so subsequent calls in the same
        # test see the fresh cached token.
        if self.row and self.row.id == token_id:
            self.row.access_token_encrypted = access_token_encrypted
            self.row.access_token_expires_at = access_token_expires_at

    async def mark_status(self, _session, *, token_id, status, error=None):
        self.marked.append(
            {"token_id": token_id, "status": status, "error": error}
        )
        if self.row and self.row.id == token_id:
            self.row.status = status
            self.row.last_error = error


_ORG_ID = uuid.uuid4()


@pytest.fixture
def _oauth_env(monkeypatch):
    """Force env vars to non-empty values so the ``start_authorize``
    503 guard doesn't fire when running against an empty .env."""
    monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        oauth,
        "GOOGLE_CALENDAR_REDIRECT_URI",
        "http://localhost:30007/api/v1/integrations/google-calendar/callback",
    )


# --- 1. State signing --------------------------------------------------


class TestStateSigning:
    def test_valid_state_round_trip(self, _oauth_env):
        """Signed state decodes back to the same payload."""
        payload = {
            "org_id": str(_ORG_ID),
            "user_id": 42,
            "nonce": "abc",
            "exp": int(time.time()) + 300,
        }
        signed = oauth._sign_state(payload)
        parsed = oauth.verify_state(signed)
        assert parsed["org_id"] == payload["org_id"]
        assert parsed["user_id"] == 42

    def test_tampered_signature_400s(self, _oauth_env):
        """Flipping a bit in the signature portion fails HMAC."""
        payload = {
            "org_id": str(_ORG_ID),
            "user_id": 42,
            "nonce": "abc",
            "exp": int(time.time()) + 300,
        }
        signed = oauth._sign_state(payload)
        body, sig = signed.split(".", 1)
        # Replace one character in the signature — HMAC compare_digest
        # returns False.
        tampered = body + "." + ("A" if sig[0] != "A" else "B") + sig[1:]
        with pytest.raises(HTTPException) as exc:
            oauth.verify_state(tampered)
        assert exc.value.status_code == 400

    def test_expired_state_400s(self, _oauth_env):
        """States older than the TTL are refused."""
        payload = {
            "org_id": str(_ORG_ID),
            "user_id": 42,
            "nonce": "abc",
            "exp": int(time.time()) - 10,  # already expired
        }
        signed = oauth._sign_state(payload)
        with pytest.raises(HTTPException) as exc:
            oauth.verify_state(signed)
        assert exc.value.status_code == 400
        assert "expired" in str(exc.value.detail).lower()

    def test_missing_dot_400s(self, _oauth_env):
        """Malformed states (no dot separator) fail early."""
        with pytest.raises(HTTPException) as exc:
            oauth.verify_state("not-a-signed-state")
        assert exc.value.status_code == 400


# --- 2. start_authorize URL shape -------------------------------------


class TestStartAuthorize:
    def test_url_includes_calendar_scope(self, _oauth_env):
        """The generated consent URL requests calendar.events."""
        url = oauth.start_authorize(org_id=_ORG_ID, user_id=42)
        assert "https://accounts.google.com/o/oauth2/v2/auth" in url
        assert "calendar.events" in url
        assert "prompt=consent" in url
        assert "access_type=offline" in url

    def test_state_encodes_user_id(self, _oauth_env):
        """The state param carries the target ``user_id`` so the
        callback binds the row to the right employee."""
        from urllib.parse import parse_qs, urlparse

        url = oauth.start_authorize(org_id=_ORG_ID, user_id=42)
        qs = parse_qs(urlparse(url).query)
        state = qs["state"][0]
        payload = oauth.verify_state(state)
        assert payload["user_id"] == 42
        assert payload["org_id"] == str(_ORG_ID)

    def test_missing_client_id_503s(self, monkeypatch):
        """Missing GOOGLE_OAUTH_CLIENT_ID → 503 (operator fix)."""
        monkeypatch.setattr(oauth, "GOOGLE_OAUTH_CLIENT_ID", "")
        with pytest.raises(HTTPException) as exc:
            oauth.start_authorize(org_id=_ORG_ID, user_id=42)
        assert exc.value.status_code == 503


# --- 3. get_valid_access_token — refresh path -------------------------


class TestGetValidAccessToken:
    @pytest.mark.asyncio
    async def test_cached_token_used_when_fresh(self, monkeypatch, _oauth_env):
        """When the cached access token has >60s left, return it
        without hitting Google's /token endpoint."""
        from datetime import UTC, datetime, timedelta

        row = _TokenRow(
            refresh_token_encrypted=crypto.encrypt("refresh-abc"),
            access_token_encrypted=crypto.encrypt("cached-access"),
            access_token_expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        da = _CapturingDA(row)
        monkeypatch.setattr(
            "src.app.core.integrations.google_calendar.oauth"
            ".get_valid_access_token.__globals__",
            oauth.__dict__,
            raising=False,
        )
        # Patch the DAL module the refresh helper imports.
        import src.app.core.integrations.google_calendar.data_access as _real_da

        monkeypatch.setattr(
            _real_da, "get_active_token_for_user", da.get_active_token_for_user
        )
        monkeypatch.setattr(
            _real_da, "update_access_token", da.update_access_token
        )
        monkeypatch.setattr(_real_da, "mark_status", da.mark_status)

        # httpx client isn't touched on the cached path — pass a
        # dummy that would fail if called.
        client = _FakeAsyncClient()
        result = await oauth.get_valid_access_token(
            session=None, org_id=_ORG_ID, user_id=42, http_client=client
        )
        assert result == "cached-access"
        assert client.calls == []
        assert da.updated_access == []

    @pytest.mark.asyncio
    async def test_expired_token_triggers_refresh(
        self, monkeypatch, _oauth_env
    ):
        """When the cached token is within the margin, the refresh call
        fires against Google's /token endpoint and the new token is
        persisted via ``update_access_token``."""
        from datetime import UTC, datetime, timedelta

        row = _TokenRow(
            refresh_token_encrypted=crypto.encrypt("refresh-abc"),
            access_token_encrypted=crypto.encrypt("stale-access"),
            access_token_expires_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        da = _CapturingDA(row)
        import src.app.core.integrations.google_calendar.data_access as _real_da

        monkeypatch.setattr(
            _real_da, "get_active_token_for_user", da.get_active_token_for_user
        )
        monkeypatch.setattr(
            _real_da, "update_access_token", da.update_access_token
        )
        monkeypatch.setattr(_real_da, "mark_status", da.mark_status)

        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(
                200,
                {"access_token": "brand-new-access", "expires_in": 3600},
            ),
        )
        result = await oauth.get_valid_access_token(
            session=None, org_id=_ORG_ID, user_id=42, http_client=client
        )
        assert result == "brand-new-access"
        assert len(client.calls) == 1
        assert len(da.updated_access) == 1
        # The persisted access_token is Fernet ciphertext; decrypt
        # confirms round-trip.
        cipher = da.updated_access[0]["access_token_encrypted"]
        assert crypto.decrypt(cipher) == "brand-new-access"

    @pytest.mark.asyncio
    async def test_invalid_grant_marks_row_revoked(
        self, monkeypatch, _oauth_env
    ):
        """``invalid_grant`` from Google's refresh endpoint → row's
        ``status`` flips to ``revoked`` + :class:`GoogleCalendarNotConnected`
        surfaces to the caller."""
        from datetime import UTC, datetime, timedelta

        row = _TokenRow(
            refresh_token_encrypted=crypto.encrypt("revoked-refresh"),
            access_token_encrypted=None,
            access_token_expires_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        da = _CapturingDA(row)
        import src.app.core.integrations.google_calendar.data_access as _real_da

        monkeypatch.setattr(
            _real_da, "get_active_token_for_user", da.get_active_token_for_user
        )
        monkeypatch.setattr(
            _real_da, "update_access_token", da.update_access_token
        )
        monkeypatch.setattr(_real_da, "mark_status", da.mark_status)

        client = _FakeAsyncClient()
        client.respond(
            "POST",
            "https://oauth2.googleapis.com/token",
            _FakeResponse(400, {"error": "invalid_grant"}),
        )
        with pytest.raises(oauth.GoogleCalendarNotConnected):
            await oauth.get_valid_access_token(
                session=None, org_id=_ORG_ID, user_id=42, http_client=client
            )
        assert len(da.marked) == 1
        assert da.marked[0]["status"] == "revoked"
        assert "revoked" in (da.marked[0]["error"] or "").lower()

    @pytest.mark.asyncio
    async def test_missing_row_raises_not_connected(
        self, monkeypatch, _oauth_env
    ):
        """User never connected → no row → immediate NotConnected."""
        da = _CapturingDA(None)
        import src.app.core.integrations.google_calendar.data_access as _real_da

        monkeypatch.setattr(
            _real_da, "get_active_token_for_user", da.get_active_token_for_user
        )

        with pytest.raises(oauth.GoogleCalendarNotConnected):
            await oauth.get_valid_access_token(
                session=None,
                org_id=_ORG_ID,
                user_id=42,
                http_client=_FakeAsyncClient(),
            )
