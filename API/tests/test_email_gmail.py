"""Step 2 — Gmail adapter tests.

Five groups:

  1. `GmailProvider` (`authorize_url`, `exchange_code`, `refresh`) —
     URL composition + token-endpoint round-trip via a stub httpx
     client (no `respx` dep; same pattern as `test_integrations_table`).
  2. `GmailClient` — request-pipeline behaviour: refresh-on-call,
     `GmailHTTPError` on 4xx, JSON decoding.
  3. `sync.backfill` + `sync.sync_incremental` — recipient matching,
     pagination, history-id capture, 404-tolerance.
  4. `send.send` — daily-cap enforcement (under cap, hard cap),
     counter rollback on Gmail-side rejection.
  5. `push.decode_pubsub_message` + payload validation — base64 +
     JSON edge cases.

Like the integrations tests these skip DB round-trip — the prod-style
`async_session()` engine isn't safe to drive from pytest-asyncio
fixtures. Manual smoke covers end-to-end DB writes.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from src.app.core.email.gmail import push as gmail_push
from src.app.core.email.gmail import send as gmail_send
from src.app.core.email.gmail import sync as gmail_sync
from src.app.core.email.gmail.client import GmailClient, GmailHTTPError
from src.app.core.email.gmail.oauth import GMAIL_SCOPES, GmailProvider
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email.oauth import TokenSet
from src.app.core.integrations import crypto

_ORG_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_account(
    **overrides,
) -> EmailAccount:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        user_id=_USER_ID,
        provider=EmailAccountProvider.gmail,
        external_account_id="asha@example.com",
        email_address="asha@example.com",
        display_name="Asha",
        access_token_enc=crypto.encrypt("current-access"),
        refresh_token_enc=crypto.encrypt("current-refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes_granted=list(GMAIL_SCOPES),
        sync_cursor=None,
        sync_state=EmailAccountSyncState.live,
        last_sync_at=None,
        last_sync_error=None,
        daily_sent_count=0,
        daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=UTC),
        connected_at=datetime(2026, 1, 1, tzinfo=UTC),
        disconnected_at=None,
        disconnected_by=None,
    )
    defaults.update(overrides)
    return EmailAccount(**defaults)


class _FakeResp:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self) -> Any:
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("fake", request=None, response=None)


class _StubHttp:
    """AsyncClient stand-in. Records every call; returns the next
    queued response. Tests configure a list of `_FakeResp` per
    method/path or by call order."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.queue: list[_FakeResp] = []

    def queue_response(self, response: _FakeResp) -> None:
        self.queue.append(response)

    async def post(self, url, *, data=None, json=None, headers=None):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "data": data,
                "json": json,
                "headers": headers,
            }
        )
        if not self.queue:
            raise AssertionError(f"unexpected POST {url}: no queued response")
        return self.queue.pop(0)

    async def get(self, url, *, params=None, headers=None):
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "params": params,
                "headers": headers,
            }
        )
        if not self.queue:
            raise AssertionError(f"unexpected GET {url}: no queued response")
        return self.queue.pop(0)

    async def request(self, method, url, *, headers=None, params=None, json=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
            }
        )
        if not self.queue:
            raise AssertionError(f"unexpected {method} {url}: no queued response")
        return self.queue.pop(0)


# --- 1. GmailProvider ----------------------------------------------------


class TestGmailProvider:
    def test_authorize_url_carries_scopes_state_redirect(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_ID",
            "test-client-id",
        )
        provider = GmailProvider()
        url = provider.authorize_url(
            state="signed-state-blob",
            redirect_uri="https://api.example.com/email/gmail/callback",
        )
        # Scopes joined with space, URL-encoded as `+` or `%20`
        assert "client_id=test-client-id" in url
        assert "state=signed-state-blob" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "gmail.modify" in url
        # Redirect URI present (URL-encoded)
        assert "callback" in url

    def test_authorize_url_503_when_client_missing(self, monkeypatch):
        monkeypatch.setattr("src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_ID", "")
        from fastapi import HTTPException

        provider = GmailProvider()
        with pytest.raises(HTTPException) as exc:
            provider.authorize_url(state="s", redirect_uri="u")
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_exchange_code_decodes_token_set(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_ID",
            "x",
        )
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_SECRET",
            "y",
        )
        http = _StubHttp()
        http.queue_response(
            _FakeResp(
                200,
                {
                    "access_token": "fresh-access",
                    "refresh_token": "fresh-refresh",
                    "expires_in": 3600,
                    "scope": " ".join(GMAIL_SCOPES),
                },
            )
        )
        tokens = await GmailProvider().exchange_code(
            code="code-123",
            redirect_uri="http://x/cb",
            http_client=http,
        )
        assert tokens.access_token == "fresh-access"
        assert tokens.refresh_token == "fresh-refresh"
        assert tokens.expires_in_seconds == 3600
        assert "https://www.googleapis.com/auth/gmail.modify" in tokens.scopes_granted
        # POST body carried the code + grant_type
        body = http.calls[0]["data"]
        assert body["code"] == "code-123"
        assert body["grant_type"] == "authorization_code"

    @pytest.mark.asyncio
    async def test_exchange_code_400_on_google_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_ID",
            "x",
        )
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_SECRET",
            "y",
        )
        http = _StubHttp()
        http.queue_response(_FakeResp(400, {"error": "invalid_grant"}))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await GmailProvider().exchange_code(
                code="bad", redirect_uri="http://x/cb", http_client=http
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_refresh_returns_new_access_token(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_ID",
            "x",
        )
        monkeypatch.setattr(
            "src.app.core.email.gmail.oauth.GOOGLE_OAUTH_CLIENT_SECRET",
            "y",
        )
        http = _StubHttp()
        # Google's refresh response normally omits refresh_token —
        # we propagate None so the caller keeps the existing one.
        http.queue_response(
            _FakeResp(
                200,
                {
                    "access_token": "refreshed-access",
                    "expires_in": 3600,
                },
            )
        )
        tokens = await GmailProvider().refresh(refresh_token="rt", http_client=http)
        assert tokens.access_token == "refreshed-access"
        assert tokens.refresh_token is None


# --- 2. GmailClient ------------------------------------------------------


class TestGmailClient:
    @pytest.mark.asyncio
    async def test_request_carries_bearer_after_refresh(self, monkeypatch):
        # Mock refresh_if_expired to return a stable TokenSet so we
        # don't drag the entire OAuth registry into a client test.
        async def fake_refresh(session, *, account):
            return TokenSet(
                access_token="usable-access",
                refresh_token=None,
                expires_in_seconds=None,
                scopes_granted=[],
            )

        monkeypatch.setattr(
            "src.app.core.email.gmail.client.email_service.refresh_if_expired",
            fake_refresh,
        )
        account = _make_account()
        http = _StubHttp()
        http.queue_response(_FakeResp(200, {"messages": [{"id": "abc"}]}))
        client = GmailClient(account=account, session=AsyncMock(), http_client=http)
        body = await client.list_messages(q="newer_than:1d")
        assert body == {"messages": [{"id": "abc"}]}
        call = http.calls[0]
        assert call["headers"]["Authorization"] == "Bearer usable-access"
        assert call["params"]["q"] == "newer_than:1d"

    @pytest.mark.asyncio
    async def test_4xx_raises_gmail_http_error(self, monkeypatch):
        async def fake_refresh(session, *, account):
            return TokenSet(
                access_token="a",
                refresh_token=None,
                expires_in_seconds=None,
                scopes_granted=[],
            )

        monkeypatch.setattr(
            "src.app.core.email.gmail.client.email_service.refresh_if_expired",
            fake_refresh,
        )
        account = _make_account()
        http = _StubHttp()
        http.queue_response(_FakeResp(404, {"error": {"message": "not found"}}))
        client = GmailClient(account=account, session=AsyncMock(), http_client=http)
        with pytest.raises(GmailHTTPError) as exc:
            await client.get_message("zzz", format="metadata")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_disconnected_account_rejected_at_init(self):
        account = _make_account(
            sync_state=EmailAccountSyncState.disconnected,
            access_token_enc=None,
            refresh_token_enc=None,
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            GmailClient(account=account, session=AsyncMock())
        assert exc.value.status_code == 409


# --- 3. sync.backfill + sync_incremental ---------------------------------


class _FakeGmailClient:
    """In-memory client stand-in that backfill / sync_incremental
    consume. We feed it canned list/get/history responses; it
    records every call."""

    def __init__(
        self,
        *,
        list_pages: list[dict],
        message_details: dict[str, dict],
        history_pages: list[dict] | None = None,
    ) -> None:
        self._list_pages = list(list_pages)
        self._messages = message_details
        self._history_pages = list(history_pages or [])
        self.list_calls = 0
        self.get_calls: list[str] = []
        self.history_calls = 0

    async def list_messages(self, *, q=None, page_token=None, max_results=100):
        self.list_calls += 1
        if not self._list_pages:
            return {"messages": []}
        return self._list_pages.pop(0)

    async def get_message(self, message_id, *, format="metadata"):
        self.get_calls.append(message_id)
        if message_id not in self._messages:
            raise GmailHTTPError(404, {"error": "not_found"})
        return self._messages[message_id]

    async def list_history(self, *, start_history_id, page_token=None, history_types=None):
        self.history_calls += 1
        if not self._history_pages:
            return {"historyId": start_history_id}
        return self._history_pages.pop(0)


class _FakeSession:
    """Session with one `execute` that returns a canned `.all()`
    result for the contact-lookup query in `_lookup_contacts_by_email`."""

    def __init__(self, *, contacts_by_email: dict[str, uuid.UUID]):
        self._map = contacts_by_email

    async def execute(self, _stmt):
        rows = [(cid, addr) for addr, cid in self._map.items()]

        class R:
            def all(self):
                return rows

        return R()


def _msg(id: str, *, headers: dict, history_id: str = "100", thread_id: str | None = None) -> dict:
    """Build a Gmail-shaped message-detail JSON."""
    return {
        "id": id,
        "threadId": thread_id or id,
        "historyId": history_id,
        "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]},
    }


class TestSyncBackfill:
    @pytest.mark.asyncio
    async def test_matched_messages_collected(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"mehta@designs.com": contact_id})
        client = _FakeGmailClient(
            list_pages=[
                {"messages": [{"id": "m1"}, {"id": "m2"}]},
                {"messages": []},
            ],
            message_details={
                "m1": _msg(
                    "m1",
                    headers={
                        "From": "Mr Mehta <mehta@designs.com>",
                        "To": "asha@example.com",
                        "Subject": "Quote for sofa",
                    },
                    history_id="500",
                ),
                "m2": _msg(
                    "m2",
                    headers={
                        "From": "stranger@unknown.com",
                        "To": "asha@example.com",
                    },
                    history_id="500",
                ),
            },
        )
        account = _make_account()
        result = await gmail_sync.backfill(account, session, client=client, days=30)
        assert result.scanned_count == 2
        assert len(result.matched) == 1
        assert result.matched[0].gmail_message_id == "m1"
        assert result.matched[0].matched_contact_id == contact_id
        assert result.matched[0].headers["subject"] == "Quote for sofa"
        # historyId from the first message becomes the new cursor.
        assert result.new_cursor == "500"

    @pytest.mark.asyncio
    async def test_pagination_walks_until_exhausted(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"a@x.com": contact_id})
        client = _FakeGmailClient(
            list_pages=[
                {
                    "messages": [{"id": "m1"}],
                    "nextPageToken": "page2",
                },
                {
                    "messages": [{"id": "m2"}],
                    "nextPageToken": None,
                },
            ],
            message_details={
                "m1": _msg("m1", headers={"From": "a@x.com"}, history_id="1"),
                "m2": _msg("m2", headers={"From": "a@x.com"}, history_id="2"),
            },
        )
        account = _make_account()
        result = await gmail_sync.backfill(account, session, client=client, days=30)
        assert client.list_calls == 2
        assert result.scanned_count == 2
        assert len(result.matched) == 2

    @pytest.mark.asyncio
    async def test_404_on_get_skips_message(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"a@x.com": contact_id})
        client = _FakeGmailClient(
            list_pages=[
                {
                    "messages": [
                        {"id": "m1"},  # exists
                        {"id": "ghost"},  # will 404 (deleted race)
                    ]
                }
            ],
            message_details={
                "m1": _msg("m1", headers={"From": "a@x.com"}, history_id="1"),
                # 'ghost' intentionally absent → 404
            },
        )
        account = _make_account()
        result = await gmail_sync.backfill(account, session, client=client, days=30)
        assert result.scanned_count == 2
        assert len(result.matched) == 1
        assert result.matched[0].gmail_message_id == "m1"


class TestSyncIncremental:
    @pytest.mark.asyncio
    async def test_history_walk_matches_added(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"mehta@designs.com": contact_id})
        client = _FakeGmailClient(
            list_pages=[],
            message_details={
                "newmsg": _msg(
                    "newmsg",
                    headers={
                        "From": "mehta@designs.com",
                        "To": "asha@example.com",
                    },
                    history_id="600",
                )
            },
            history_pages=[
                {
                    "historyId": "600",
                    "history": [
                        {
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "newmsg",
                                        "threadId": "newmsg",
                                    }
                                }
                            ]
                        }
                    ],
                }
            ],
        )
        account = _make_account(sync_cursor="500")
        result = await gmail_sync.sync_incremental(account, session, client=client)
        assert result.scanned_count == 1
        assert len(result.matched) == 1
        assert result.new_cursor == "600"
        assert result.matched[0].matched_contact_id == contact_id

    @pytest.mark.asyncio
    async def test_no_cursor_raises(self):
        session = _FakeSession(contacts_by_email={})
        account = _make_account(sync_cursor=None)
        client = _FakeGmailClient(list_pages=[], message_details={}, history_pages=[])
        with pytest.raises(RuntimeError, match="no sync_cursor"):
            await gmail_sync.sync_incremental(account, session, client=client)


# --- 4. send.send --------------------------------------------------------


class _SendStubClient:
    """Minimal Gmail client stand-in just for `send_message`."""

    def __init__(self, *, response: dict | None = None, raise_with: Exception | None = None):
        self._response = response
        self._raise = raise_with
        self.calls: list[dict] = []

    async def send_message(self, *, raw_b64url, thread_id=None):
        self.calls.append({"raw_b64url": raw_b64url, "thread_id": thread_id})
        if self._raise is not None:
            raise self._raise
        return self._response or {"id": "sent-msg-id", "threadId": "t"}


class _CapturingSession:
    """Tracks commit count + lets `await session.commit()` succeed."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass


class TestSend:
    @pytest.mark.asyncio
    async def test_send_increments_counter_and_returns_ids(self):
        account = _make_account(daily_sent_count=10)
        session = _CapturingSession()
        client = _SendStubClient(response={"id": "msg-xyz", "threadId": "thr-abc"})
        result = await gmail_send.send(
            account,
            session,
            raw_mime=b"From: a@x\r\nTo: b@y\r\nSubject: t\r\n\r\nbody",
            client=client,
            soft_cap=200,
            hard_cap=500,
        )
        assert result.gmail_message_id == "msg-xyz"
        assert result.gmail_thread_id == "thr-abc"
        assert result.daily_sent_after == 11
        assert account.daily_sent_count == 11
        # raw_b64url is URL-safe base64 of the input, no padding.
        assert client.calls[0]["raw_b64url"].startswith("RnJvbTo")

    @pytest.mark.asyncio
    async def test_hard_cap_blocks_send(self):
        account = _make_account(daily_sent_count=500)
        session = _CapturingSession()
        client = _SendStubClient(response={"id": "x"})
        with pytest.raises(gmail_send.DailyCapExceeded) as exc:
            await gmail_send.send(
                account,
                session,
                raw_mime=b"x",
                client=client,
                soft_cap=200,
                hard_cap=500,
            )
        assert exc.value.status_code == 429
        # Cap-check fires BEFORE Gmail call — no send attempted.
        assert client.calls == []
        # Counter unchanged.
        assert account.daily_sent_count == 500

    @pytest.mark.asyncio
    async def test_gmail_failure_rolls_back_counter(self):
        account = _make_account(daily_sent_count=10)
        session = _CapturingSession()
        client = _SendStubClient(raise_with=GmailHTTPError(503, {"err": "down"}))
        with pytest.raises(GmailHTTPError):
            await gmail_send.send(
                account,
                session,
                raw_mime=b"x",
                client=client,
                soft_cap=200,
                hard_cap=500,
            )
        # The counter went up to 11 then back to 10.
        assert account.daily_sent_count == 10
        # commit fired twice — once for the +1, once for the -1.
        assert session.commits == 2

    @pytest.mark.asyncio
    async def test_near_soft_cap_flag(self):
        account = _make_account(daily_sent_count=189)  # 0.9 * 200 = 180
        session = _CapturingSession()
        client = _SendStubClient(response={"id": "x", "threadId": "y"})
        result = await gmail_send.send(
            account,
            session,
            raw_mime=b"x",
            client=client,
            soft_cap=200,
            hard_cap=500,
        )
        assert result.near_soft_cap is True


# --- 5. push.decode_pubsub_message --------------------------------------


class TestPushDecode:
    def test_happy_path(self):
        payload = {"emailAddress": "asha@example.com", "historyId": 12345}
        envelope = {
            "message": {
                "data": base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode(
                    "ascii"
                ),
                "messageId": "pubsub-msg-1",
                "publishTime": "2026-06-11T10:00:00Z",
            },
            "subscription": "projects/p/subscriptions/s",
        }
        decoded = gmail_push.decode_pubsub_message(envelope)
        assert decoded["email_address"] == "asha@example.com"
        assert decoded["history_id"] == "12345"
        assert decoded["message_id"] == "pubsub-msg-1"

    def test_missing_message_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            gmail_push.decode_pubsub_message({})
        assert exc.value.status_code == 400

    def test_non_b64_data_400(self):
        from fastapi import HTTPException

        envelope = {"message": {"data": "!!!not-base64!!!"}}
        with pytest.raises(HTTPException) as exc:
            gmail_push.decode_pubsub_message(envelope)
        assert exc.value.status_code == 400

    def test_missing_inner_fields_400(self):
        from fastapi import HTTPException

        envelope = {
            "message": {
                "data": base64.urlsafe_b64encode(
                    json.dumps({"emailAddress": "x@y"}).encode()
                ).decode("ascii")
            }
        }
        with pytest.raises(HTTPException) as exc:
            gmail_push.decode_pubsub_message(envelope)
        assert exc.value.status_code == 400
        # The exception is about the missing historyId.
        assert "historyId" in str(exc.value.detail)


# --- 6. address-extraction helpers --------------------------------------


class TestAddressExtraction:
    def test_bracketed_form(self):
        assert gmail_sync._extract_addresses("Asha Patel <asha@example.com>") == [
            "asha@example.com"
        ]

    def test_bare_form(self):
        assert gmail_sync._extract_addresses("bob@y.com") == ["bob@y.com"]

    def test_multiple_comma_separated(self):
        addrs = gmail_sync._extract_addresses('A <a@x.com>, b@y.com, "C, Jr" <c@z.com>')
        assert "a@x.com" in addrs
        assert "b@y.com" in addrs
        assert "c@z.com" in addrs

    def test_lowercases(self):
        assert gmail_sync._extract_addresses("ASHA@Example.COM") == ["asha@example.com"]

    def test_empty(self):
        assert gmail_sync._extract_addresses("") == []
