"""Step 3 — Microsoft Graph adapter tests.

Six groups:

  1. `MicrosoftProvider` — URL composition, token-exchange round-trip,
     refresh-token rotation (rotates, unlike Google).
  2. `GraphClient` — bearer header, 429 backoff, GraphHTTPError on 4xx.
  3. `sync.backfill` + `sync_incremental` — filter walk, delta-link
     seeding, 410 → `delta_link_expired=True`.
  4. `send.send` — daily cap (hard blocks, rollback on Graph failure).
  5. `webhook` — `client_state_for` HMAC, `decode_notification`
     envelope parse, `assert_client_state` constant-time compare.
  6. `_collect_addresses` + `_extract_headers` — Graph's normalised
     shape → standard rfc-822-ish header dict.

Same convention as `test_email_gmail.py`: no DB, AsyncMock + stub
clients. Manual smoke covers end-to-end DB writes.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.app.core.email.microsoft import send as ms_send
from src.app.core.email.microsoft import sync as ms_sync
from src.app.core.email.microsoft import webhook as ms_webhook
from src.app.core.email.microsoft.client import GraphClient, GraphHTTPError
from src.app.core.email.microsoft.oauth import (
    MICROSOFT_SCOPES,
    MicrosoftProvider,
)
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email.oauth import TokenSet
from src.app.core.integrations import crypto

_ORG_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_account(**overrides) -> EmailAccount:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        user_id=_USER_ID,
        provider=EmailAccountProvider.microsoft,
        external_account_id="aad-object-id",
        email_address="asha@contoso.com",
        display_name="Asha Patel",
        access_token_enc=crypto.encrypt("current-access"),
        refresh_token_enc=crypto.encrypt("current-refresh"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes_granted=list(MICROSOFT_SCOPES),
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


# --- HTTP stubs ---------------------------------------------------------


class _FakeResp:
    def __init__(
        self,
        status_code: int,
        body: Any,
        *,
        headers: dict | None = None,
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.content = (
            content if content is not None else (b"" if body is None else json.dumps(body).encode())
        )
        self.text = body if isinstance(body, str) else json.dumps(body) if body else ""

    def json(self) -> Any:
        if isinstance(self._body, (dict, list)):
            return self._body
        raise ValueError("not json")


class _StubHttp:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.queue: list[_FakeResp] = []

    def queue_response(self, response: _FakeResp) -> None:
        self.queue.append(response)

    async def post(self, url, *, data=None, json=None, headers=None):
        self.calls.append(
            {"method": "POST", "url": url, "data": data, "json": json, "headers": headers}
        )
        if not self.queue:
            raise AssertionError(f"unexpected POST {url}")
        return self.queue.pop(0)

    async def get(self, url, *, params=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers})
        if not self.queue:
            raise AssertionError(f"unexpected GET {url}")
        return self.queue.pop(0)

    async def request(self, method, url, *, headers=None, params=None, json=None, content=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "content": content,
            }
        )
        if not self.queue:
            raise AssertionError(f"unexpected {method} {url}")
        return self.queue.pop(0)


# --- 1. MicrosoftProvider -----------------------------------------------


class TestMicrosoftProvider:
    def test_authorize_url_carries_scopes_state(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_ID",
            "test-client",
        )
        url = MicrosoftProvider().authorize_url(
            state="signed-state",
            redirect_uri="https://api.example.com/email/microsoft/callback",
        )
        assert "login.microsoftonline.com" in url
        assert "client_id=test-client" in url
        assert "state=signed-state" in url
        assert "prompt=consent" in url
        assert "Mail.ReadWrite" in url
        assert "offline_access" in url

    def test_authorize_url_503_when_client_missing(self, monkeypatch):
        monkeypatch.setattr("src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_ID", "")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            MicrosoftProvider().authorize_url(state="s", redirect_uri="u")
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_exchange_code_decodes_token_set(self, monkeypatch):
        monkeypatch.setattr("src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_ID", "x")
        monkeypatch.setattr("src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_SECRET", "y")
        http = _StubHttp()
        http.queue_response(
            _FakeResp(
                200,
                {
                    "access_token": "fresh-access",
                    "refresh_token": "fresh-refresh",
                    "expires_in": 3600,
                    "scope": " ".join(MICROSOFT_SCOPES),
                },
            )
        )
        tokens = await MicrosoftProvider().exchange_code(
            code="code-123",
            redirect_uri="http://x/cb",
            http_client=http,
        )
        assert tokens.access_token == "fresh-access"
        assert tokens.refresh_token == "fresh-refresh"
        assert tokens.expires_in_seconds == 3600
        assert "Mail.ReadWrite" in tokens.scopes_granted

    @pytest.mark.asyncio
    async def test_refresh_rotates_refresh_token(self, monkeypatch):
        """Microsoft DOES return a new refresh_token on refresh —
        opposite of Google's behaviour. The TokenSet must carry it
        so `service.refresh_if_expired` persists the rotation."""
        monkeypatch.setattr("src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_ID", "x")
        monkeypatch.setattr("src.app.core.email.microsoft.oauth.MICROSOFT_CLIENT_SECRET", "y")
        http = _StubHttp()
        http.queue_response(
            _FakeResp(
                200,
                {
                    "access_token": "refreshed-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                },
            )
        )
        tokens = await MicrosoftProvider().refresh(refresh_token="old-refresh", http_client=http)
        assert tokens.access_token == "refreshed-access"
        assert tokens.refresh_token == "rotated-refresh"


# --- 2. GraphClient -----------------------------------------------------


async def _fake_refresh(session, *, account):
    """Stand-in for email_service.refresh_if_expired — returns a
    stable plaintext access token without touching the OAuth registry."""
    return TokenSet(
        access_token="usable-access",
        refresh_token=None,
        expires_in_seconds=None,
        scopes_granted=[],
    )


class TestGraphClient:
    @pytest.mark.asyncio
    async def test_request_carries_bearer(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.microsoft.client.email_service.refresh_if_expired",
            _fake_refresh,
        )
        account = _make_account()
        http = _StubHttp()
        http.queue_response(_FakeResp(200, {"value": [{"id": "msg-1"}]}))
        client = GraphClient(account=account, session=AsyncMock(), http_client=http)
        body = await client.list_messages(
            filter_expr="receivedDateTime ge 2026-05-12T00:00:00Z",
            select="id,subject",
        )
        assert body == {"value": [{"id": "msg-1"}]}
        call = http.calls[0]
        assert call["headers"]["Authorization"] == "Bearer usable-access"
        assert call["params"]["$filter"] == "receivedDateTime ge 2026-05-12T00:00:00Z"

    @pytest.mark.asyncio
    async def test_429_honours_retry_after_then_succeeds(self, monkeypatch):
        # Skip the actual sleep — pytest doesn't want to wait 30s.
        monkeypatch.setattr(
            "src.app.core.email.microsoft.client.email_service.refresh_if_expired",
            _fake_refresh,
        )
        slept: list[float] = []

        async def fake_sleep(s):
            slept.append(s)

        monkeypatch.setattr("src.app.core.email.microsoft.client.asyncio.sleep", fake_sleep)
        http = _StubHttp()
        http.queue_response(_FakeResp(429, {"err": "throttled"}, headers={"retry-after": "5"}))
        http.queue_response(_FakeResp(200, {"value": []}))
        account = _make_account()
        client = GraphClient(account=account, session=AsyncMock(), http_client=http)
        body = await client.list_messages()
        assert body == {"value": []}
        assert slept == [5.0]

    @pytest.mark.asyncio
    async def test_4xx_raises_graph_http_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.microsoft.client.email_service.refresh_if_expired",
            _fake_refresh,
        )
        http = _StubHttp()
        http.queue_response(_FakeResp(410, {"error": {"code": "syncStateInvalid"}}))
        account = _make_account()
        client = GraphClient(account=account, session=AsyncMock(), http_client=http)
        with pytest.raises(GraphHTTPError) as exc:
            await client.get_absolute(
                "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=stale"
            )
        assert exc.value.status_code == 410

    @pytest.mark.asyncio
    async def test_disconnected_account_rejected_at_init(self):
        from fastapi import HTTPException

        account = _make_account(
            sync_state=EmailAccountSyncState.disconnected,
            access_token_enc=None,
            refresh_token_enc=None,
        )
        with pytest.raises(HTTPException) as exc:
            GraphClient(account=account, session=AsyncMock())
        assert exc.value.status_code == 409


# --- 3. sync.backfill + sync_incremental --------------------------------


def _ms_msg(
    msg_id: str,
    *,
    from_addr: str,
    to_addrs: list[str] | None = None,
    subject: str = "",
    conversation_id: str | None = None,
) -> dict:
    """Build a Graph-shaped message metadata blob."""
    return {
        "id": msg_id,
        "subject": subject,
        "conversationId": conversation_id or msg_id,
        "internetMessageId": f"<{msg_id}@graph.local>",
        "receivedDateTime": "2026-06-10T10:00:00Z",
        "from": {"emailAddress": {"name": "Sender", "address": from_addr}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in (to_addrs or [])],
    }


class _FakeGraphClient:
    """In-memory client; backfill/sync_incremental consume it."""

    def __init__(
        self,
        *,
        list_pages: list[dict],
        delta_pages: list[dict] | None = None,
        get_absolute_pages: dict[str, dict] | None = None,
    ) -> None:
        self._list_pages = list(list_pages)
        self._delta_pages = list(delta_pages or [])
        self._abs = dict(get_absolute_pages or {})
        self.list_calls = 0
        self.delta_calls = 0
        self.absolute_calls: list[str] = []

    async def list_messages(self, *, filter_expr=None, select=None, top=50, order_by=None):
        self.list_calls += 1
        if not self._list_pages:
            return {"value": []}
        return self._list_pages.pop(0)

    async def list_messages_delta(self, *, select=None, top=50):
        self.delta_calls += 1
        if not self._delta_pages:
            return {"value": [], "@odata.deltaLink": "delta://seeded"}
        return self._delta_pages.pop(0)

    async def get_absolute(self, url):
        self.absolute_calls.append(url)
        if url not in self._abs:
            raise GraphHTTPError(404, {"error": "no canned response"})
        return self._abs[url]


class _FakeSession:
    def __init__(self, *, contacts_by_email: dict[str, uuid.UUID]):
        self._map = contacts_by_email

    async def execute(self, _stmt):
        rows = [(cid, addr) for addr, cid in self._map.items()]

        class R:
            def all(self):
                return rows

        return R()


class TestSyncBackfill:
    @pytest.mark.asyncio
    async def test_filter_walk_matches_recipients(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"mehta@designs.com": contact_id})
        client = _FakeGraphClient(
            list_pages=[
                {
                    "value": [
                        _ms_msg(
                            "m1",
                            from_addr="mehta@designs.com",
                            to_addrs=["asha@contoso.com"],
                            subject="Quote for sofa",
                        ),
                        _ms_msg(
                            "m2",
                            from_addr="stranger@nowhere.com",
                            to_addrs=["asha@contoso.com"],
                        ),
                    ]
                }
            ],
            delta_pages=[{"value": [], "@odata.deltaLink": "delta://seeded-cursor"}],
        )
        account = _make_account()
        result = await ms_sync.backfill(account, session, client=client, days=30)
        assert result.scanned_count == 2
        assert len(result.matched) == 1
        assert result.matched[0].graph_message_id == "m1"
        assert result.matched[0].matched_contact_id == contact_id
        assert result.matched[0].headers["subject"] == "Quote for sofa"
        # Delta cursor was seeded after the filter walk.
        assert result.new_cursor == "delta://seeded-cursor"

    @pytest.mark.asyncio
    async def test_pagination_follows_nextlink(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"a@x.com": contact_id})
        client = _FakeGraphClient(
            list_pages=[
                {
                    "value": [
                        _ms_msg("m1", from_addr="a@x.com", to_addrs=["asha@contoso.com"]),
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=p2",
                }
            ],
            get_absolute_pages={
                "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=p2": {
                    "value": [
                        _ms_msg("m2", from_addr="a@x.com", to_addrs=["asha@contoso.com"]),
                    ]
                }
            },
            delta_pages=[{"value": [], "@odata.deltaLink": "delta://seeded"}],
        )
        account = _make_account()
        result = await ms_sync.backfill(account, session, client=client, days=30)
        assert result.scanned_count == 2
        assert len(result.matched) == 2
        assert client.absolute_calls == [
            "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=p2"
        ]


class TestSyncIncremental:
    @pytest.mark.asyncio
    async def test_walks_delta_chain_and_returns_new_cursor(self):
        contact_id = uuid.uuid4()
        session = _FakeSession(contacts_by_email={"mehta@designs.com": contact_id})
        client = _FakeGraphClient(
            list_pages=[],
            get_absolute_pages={
                "delta://stored-cursor": {
                    "value": [
                        _ms_msg(
                            "m-new", from_addr="mehta@designs.com", to_addrs=["asha@contoso.com"]
                        ),
                    ],
                    "@odata.deltaLink": "delta://new-cursor",
                }
            },
        )
        account = _make_account(sync_cursor="delta://stored-cursor")
        result = await ms_sync.sync_incremental(account, session, client=client)
        assert result.scanned_count == 1
        assert len(result.matched) == 1
        assert result.new_cursor == "delta://new-cursor"
        assert result.delta_link_expired is False

    @pytest.mark.asyncio
    async def test_410_marks_delta_expired(self):
        session = _FakeSession(contacts_by_email={})
        client = _FakeGraphClient(
            list_pages=[],
            get_absolute_pages={},  # any get_absolute will 404
        )

        # Override get_absolute to raise 410 specifically.
        async def raise_410(_url):
            raise GraphHTTPError(410, {"error": "syncStateInvalid"})

        client.get_absolute = raise_410  # type: ignore[method-assign]
        account = _make_account(sync_cursor="delta://stale-cursor")
        result = await ms_sync.sync_incremental(account, session, client=client)
        assert result.delta_link_expired is True

    @pytest.mark.asyncio
    async def test_no_cursor_raises(self):
        session = _FakeSession(contacts_by_email={})
        client = _FakeGraphClient(list_pages=[])
        account = _make_account(sync_cursor=None)
        with pytest.raises(RuntimeError, match="no sync_cursor"):
            await ms_sync.sync_incremental(account, session, client=client)


# --- 4. send.send -------------------------------------------------------


class _SendStubGraph:
    def __init__(self, *, raise_with: Exception | None = None) -> None:
        self._raise = raise_with
        self.calls: list[dict] = []

    async def send_raw(self, *, raw_b64):
        self.calls.append({"raw_b64": raw_b64})
        if self._raise is not None:
            raise self._raise


class _CapturingSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass


class TestSend:
    @pytest.mark.asyncio
    async def test_send_increments_counter(self):
        account = _make_account(daily_sent_count=10)
        session = _CapturingSession()
        client = _SendStubGraph()
        result = await ms_send.send(
            account,
            session,
            raw_mime=b"From: a\r\nTo: b\r\n\r\nbody",
            client=client,
            soft_cap=200,
            hard_cap=500,
        )
        assert result.provider_message_id is None
        assert result.daily_sent_after == 11
        assert account.daily_sent_count == 11
        # Body is base64 (NOT url-safe — sendMail wants standard b64).
        assert client.calls[0]["raw_b64"].endswith(
            base64.b64encode(b"From: a\r\nTo: b\r\n\r\nbody").decode("ascii")
        )

    @pytest.mark.asyncio
    async def test_hard_cap_blocks_send(self):
        account = _make_account(daily_sent_count=500)
        session = _CapturingSession()
        client = _SendStubGraph()
        with pytest.raises(ms_send.DailyCapExceeded) as exc:
            await ms_send.send(
                account,
                session,
                raw_mime=b"x",
                client=client,
                soft_cap=200,
                hard_cap=500,
            )
        assert exc.value.status_code == 429
        assert client.calls == []
        assert account.daily_sent_count == 500

    @pytest.mark.asyncio
    async def test_graph_failure_rolls_back_counter(self):
        account = _make_account(daily_sent_count=10)
        session = _CapturingSession()
        client = _SendStubGraph(raise_with=GraphHTTPError(503, {"err": "down"}))
        with pytest.raises(GraphHTTPError):
            await ms_send.send(
                account,
                session,
                raw_mime=b"x",
                client=client,
                soft_cap=200,
                hard_cap=500,
            )
        assert account.daily_sent_count == 10
        # Two commits: +1 then -1.
        assert session.commits == 2


# --- 5. webhook --------------------------------------------------------


class TestWebhook:
    def test_client_state_deterministic(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.microsoft.webhook.JWT_SECRET_KEY",
            "test-key",
        )
        aid = uuid.uuid4()
        s1 = ms_webhook.client_state_for(aid)
        s2 = ms_webhook.client_state_for(aid)
        assert s1 == s2
        assert len(s1) == 32

    def test_client_state_unique_per_account(self, monkeypatch):
        monkeypatch.setattr(
            "src.app.core.email.microsoft.webhook.JWT_SECRET_KEY",
            "test-key",
        )
        s1 = ms_webhook.client_state_for(uuid.uuid4())
        s2 = ms_webhook.client_state_for(uuid.uuid4())
        assert s1 != s2

    def test_decode_notification_happy(self):
        envelope = {
            "value": [
                {
                    "subscriptionId": "sub-1",
                    "clientState": "abc",
                    "changeType": "created",
                    "resource": "Users/x/Messages/y",
                }
            ]
        }
        items = ms_webhook.decode_notification(envelope)
        assert len(items) == 1
        assert items[0]["subscriptionId"] == "sub-1"

    def test_decode_notification_missing_value_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            ms_webhook.decode_notification({})
        assert exc.value.status_code == 400

    def test_assert_client_state_match(self):
        ms_webhook.assert_client_state({"clientState": "abc"}, expected="abc")  # no raise

    def test_assert_client_state_mismatch_401(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            ms_webhook.assert_client_state({"clientState": "wrong"}, expected="abc")
        assert exc.value.status_code == 401


# --- 6. Address + header helpers ---------------------------------------


class TestAddressExtraction:
    def test_collect_addresses_from_to_cc_bcc(self):
        msg = {
            "from": {"emailAddress": {"address": "FROM@x.com"}},
            "toRecipients": [
                {"emailAddress": {"address": "to1@y.com"}},
                {"emailAddress": {"address": "to2@y.com"}},
            ],
            "ccRecipients": [{"emailAddress": {"address": "cc@z.com"}}],
            "bccRecipients": [{"emailAddress": {"address": "bcc@w.com"}}],
        }
        addrs = ms_sync._collect_addresses(msg)
        assert "from@x.com" in addrs
        assert "to1@y.com" in addrs
        assert "cc@z.com" in addrs
        assert "bcc@w.com" in addrs

    def test_collect_addresses_handles_missing(self):
        assert ms_sync._collect_addresses({}) == []
        assert ms_sync._collect_addresses({"from": {}, "toRecipients": []}) == []

    def test_extract_headers_includes_subject_and_conversation(self):
        msg = {
            "id": "m1",
            "subject": "Hello",
            "internetMessageId": "<m1@x>",
            "conversationId": "thread-abc",
            "from": {"emailAddress": {"name": "Mr Mehta", "address": "mehta@x.com"}},
            "toRecipients": [{"emailAddress": {"address": "asha@y.com"}}],
            "sentDateTime": "2026-06-10T10:00:00Z",
        }
        h = ms_sync._extract_headers(msg)
        assert h["subject"] == "Hello"
        assert h["message-id"] == "<m1@x>"
        assert h["from"] == "Mr Mehta <mehta@x.com>"
        assert h["to"] == "asha@y.com"
        assert h["x-graph-conversation-id"] == "thread-abc"
        assert h["date"] == "2026-06-10T10:00:00Z"
