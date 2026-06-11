"""Step 5 — Conversations email adapter tests.

Five groups:

  1. `email_threading` — pure functions: extract_message_id,
     extract_thread_keys, normalize_subject (Re:/Fwd:/Aw:/Antw:/Sv:
     prefixes).
  2. `EmailAdapter` Protocol guard rails — `.send()` and
     `.parse_webhook()` both 400 with "use send_email" instructions.
  3. `_build_outbound_mime` — From/To/Subject + Message-ID +
     threading headers + multipart alt body.
  4. `send_email` flow (via mocked provider send) — happy path,
     wrong-user 403, disconnected 409, missing contact 400, cap
     surfaces as HardCapExceeded(429).
  5. `receive_email` flow — Message-ID threading, References-chain
     threading, subject-fallback threading, fresh conversation
     when nothing matches, dedupe on RFC-id, no contact_id → drop.

Convention: no DB. Stub `async_session()` so the receive path's
"open session" call yields a `_CapturingSession`. Stub
`email_service.get_account` + `activities_log` + `notify` + audit.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from src.app.core.conversations.adapters import email as email_adapter
from src.app.core.conversations.adapters.email_threading import (
    extract_message_id,
    extract_thread_keys,
    normalize_subject,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)


# --- shared fixtures ---------------------------------------------------


_ORG_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_account(**overrides) -> EmailAccount:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=_ORG_ID,
        user_id=_USER_ID,
        provider=EmailAccountProvider.gmail,
        external_account_id="asha@yourstore.com",
        email_address="asha@yourstore.com",
        display_name="Asha Patel",
        access_token_enc="enc",
        refresh_token_enc="enc",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes_granted=[],
        sync_cursor="history-1",
        sync_state=EmailAccountSyncState.live,
        last_sync_at=None,
        last_sync_error=None,
        daily_sent_count=0,
        daily_sent_reset_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        disconnected_at=None,
        disconnected_by=None,
    )
    defaults.update(overrides)
    return EmailAccount(**defaults)


# --- 1. email_threading --------------------------------------------


class TestExtractMessageId:
    def test_lowercase_key(self):
        assert extract_message_id(
            {"message-id": "<abc@x.com>"}
        ) == "abc@x.com"

    def test_camelcase_key(self):
        assert extract_message_id(
            {"Message-ID": "<abc@x.com>"}
        ) == "abc@x.com"

    def test_unbracketed(self):
        assert extract_message_id(
            {"message-id": "abc@x.com"}
        ) == "abc@x.com"

    def test_missing(self):
        assert extract_message_id({}) == ""

    def test_blank(self):
        assert extract_message_id({"message-id": ""}) == ""


class TestExtractThreadKeys:
    def test_in_reply_to(self):
        keys = extract_thread_keys(
            {"in-reply-to": "<parent@x.com>"}
        )
        assert keys == {"parent@x.com"}

    def test_references_chain(self):
        keys = extract_thread_keys(
            {"references": "<a@x> <b@x>\n <c@y>"}
        )
        assert keys == {"a@x", "b@x", "c@y"}

    def test_combined(self):
        keys = extract_thread_keys(
            {
                "in-reply-to": "<latest@y.com>",
                "references": "<a@x> <b@x>",
            }
        )
        assert keys == {"latest@y.com", "a@x", "b@x"}

    def test_none(self):
        assert extract_thread_keys({}) == set()


class TestNormalizeSubject:
    def test_strips_re(self):
        assert (
            normalize_subject("Re: Quote for sofa")
            == "quote for sofa"
        )

    def test_strips_repeated_re(self):
        assert (
            normalize_subject("Re: Re: Re: Quote for sofa")
            == "quote for sofa"
        )

    def test_strips_outlook_numbered_re(self):
        assert (
            normalize_subject("Re[2]: Quote for sofa")
            == "quote for sofa"
        )

    def test_strips_fwd(self):
        assert normalize_subject("Fwd: Quote") == "quote"

    def test_strips_german_aw(self):
        assert normalize_subject("AW: Quote") == "quote"

    def test_strips_scandinavian_sv(self):
        assert normalize_subject("SV: Quote") == "quote"

    def test_lowercases(self):
        assert normalize_subject("HELLO") == "hello"

    def test_empty(self):
        assert normalize_subject("") == ""
        assert normalize_subject(None) == ""


# --- 2. EmailAdapter Protocol guard rails --------------------------


class TestProtocolGuardRails:
    @pytest.mark.asyncio
    async def test_send_raises_use_send_email(self):
        with pytest.raises(email_adapter.EmailUseSendEmailEndpoint) as exc:
            await email_adapter.EmailAdapter().send(
                org_id=_ORG_ID,
                external_id="x@y.com",
                text="hi",
                attachments=[],
            )
        assert exc.value.status_code == 400

    def test_parse_webhook_raises_use_send_email(self):
        with pytest.raises(email_adapter.EmailUseSendEmailEndpoint):
            email_adapter.EmailAdapter().parse_webhook({})


# --- 3. _build_outbound_mime ---------------------------------------


class TestBuildOutboundMime:
    def test_minimal_text_email(self):
        msg = email_adapter._build_outbound_mime(
            from_email="asha@x.com",
            from_name="Asha",
            to_email="mehta@designs.com",
            to_name="Mr Mehta",
            subject="Hello",
            body_text="Just a text body.",
            body_html=None,
            message_id="<own@furnicrm.app>",
            in_reply_to=None,
        )
        assert msg["From"] == '"Asha" <asha@x.com>'
        assert msg["To"] == '"Mr Mehta" <mehta@designs.com>'
        assert msg["Subject"] == "Hello"
        assert msg["Message-ID"] == "<own@furnicrm.app>"
        assert "In-Reply-To" not in msg
        assert "References" not in msg
        body = msg.get_content().strip()
        assert body == "Just a text body."

    def test_reply_sets_threading_headers(self):
        msg = email_adapter._build_outbound_mime(
            from_email="asha@x.com",
            from_name=None,
            to_email="m@d.com",
            to_name=None,
            subject="Re: Quote",
            body_text="hi",
            body_html=None,
            message_id="<own2@furnicrm.app>",
            in_reply_to="parent@d.com",
        )
        assert msg["In-Reply-To"] == "<parent@d.com>"
        assert msg["References"] == "<parent@d.com>"

    def test_html_alternative(self):
        msg = email_adapter._build_outbound_mime(
            from_email="a@x.com",
            from_name=None,
            to_email="b@y.com",
            to_name=None,
            subject="Subj",
            body_text="hi text",
            body_html="<p>hi html</p>",
            message_id="<own@furnicrm.app>",
            in_reply_to=None,
        )
        # Multipart with text + html parts.
        assert msg.is_multipart()


# --- 4. send_email flow --------------------------------------------


class _CapturingSession:
    """Stand-in for AsyncSession. Captures `session.add` and ORM
    SELECT/UPDATE invocations through a `_select_responder` map the
    test sets up."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0
        # Maps a SELECT statement matcher → canned result.
        # We won't actually match — tests will preload `_canned_*`
        # attributes and the stubbed `execute` returns the next one.
        self.canned_responses: list = []

    def queue(self, response) -> None:
        self.canned_responses.append(response)

    async def execute(self, _stmt):
        if not self.canned_responses:
            raise AssertionError("no canned response queued")
        return self.canned_responses.pop(0)

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        pass

    async def flush(self):
        pass


class _ScalarOneOrNone:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v

    def scalars(self):
        return self

    def first(self):
        return self._v

    def all(self):
        return [self._v] if self._v is not None else []


class _AllRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeContact:
    def __init__(self, *, id=None, email="mehta@designs.com",
                 full_name="Mr Mehta"):
        self.id = id or uuid.uuid4()
        self.email = email
        self.full_name = full_name


class _FakeConversation:
    def __init__(self):
        self.id = uuid.uuid4()
        self.org_id = _ORG_ID
        self.contact_id = uuid.uuid4()
        self.channel = ConversationChannel.email
        self.last_message_at = None
        self.unread_count = 0
        self.assigned_to_id = None
        self.status = ConversationStatus.open
        self.external_id = "mehta@designs.com"


@pytest.fixture(autouse=True)
def patch_external_io(monkeypatch):
    """Stub activities.log, notify, audit.log so tests don't open
    their own sessions."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(
        "src.app.core.conversations.adapters.email.activities_log",
        _noop,
    )
    monkeypatch.setattr(
        "src.app.core.conversations.adapters.email.notify",
        _noop,
    )
    monkeypatch.setattr(
        "src.app.core.conversations.adapters.email.audit.log",
        _noop,
    )


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_account_not_found_404(self, monkeypatch):
        async def fake_get_account(_sess, *, account_id):
            return None

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )
        from fastapi import HTTPException

        session = _CapturingSession()
        with pytest.raises(HTTPException) as exc:
            await email_adapter.send_email(
                session,
                org_id=_ORG_ID,
                sender_user_id=_USER_ID,
                account_id=uuid.uuid4(),
                contact_id=uuid.uuid4(),
                subject="x",
                body_text="x",
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_user_403(self, monkeypatch):
        wrong_user = uuid.uuid4()
        account = _make_account(user_id=wrong_user)

        async def fake_get_account(_sess, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )
        from fastapi import HTTPException

        session = _CapturingSession()
        with pytest.raises(HTTPException) as exc:
            await email_adapter.send_email(
                session,
                org_id=_ORG_ID,
                sender_user_id=_USER_ID,  # Doesn't match account.user_id
                account_id=account.id,
                contact_id=uuid.uuid4(),
                subject="x",
                body_text="x",
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_disconnected_409(self, monkeypatch):
        account = _make_account(
            sync_state=EmailAccountSyncState.disconnected,
            access_token_enc=None,
        )

        async def fake_get_account(_sess, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )
        from fastapi import HTTPException

        session = _CapturingSession()
        with pytest.raises(HTTPException) as exc:
            await email_adapter.send_email(
                session,
                org_id=_ORG_ID,
                sender_user_id=_USER_ID,
                account_id=account.id,
                contact_id=uuid.uuid4(),
                subject="x",
                body_text="x",
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_missing_contact_email_400(self, monkeypatch):
        account = _make_account()
        contact = _FakeContact(email=None)

        async def fake_get_account(_sess, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )
        from fastapi import HTTPException

        session = _CapturingSession()
        session.queue(_ScalarOneOrNone(contact))  # Contact lookup
        with pytest.raises(HTTPException) as exc:
            await email_adapter.send_email(
                session,
                org_id=_ORG_ID,
                sender_user_id=_USER_ID,
                account_id=account.id,
                contact_id=contact.id,
                subject="x",
                body_text="x",
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_happy_send_gmail(self, monkeypatch):
        account = _make_account(provider=EmailAccountProvider.gmail)
        contact = _FakeContact()

        async def fake_get_account(_sess, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )

        # Mock the Gmail send. send() returns a SendResult dataclass.
        from src.app.core.email.gmail.send import SendResult as GmailSR

        async def fake_gmail_send(_account, _session, *, raw_mime,
                                   thread_id=None):
            return GmailSR(
                gmail_message_id="gm-msg-xyz",
                gmail_thread_id="gm-thr-abc",
                daily_sent_after=1,
                near_soft_cap=False,
            )

        from src.app.core.email.gmail import send as gmail_send_mod

        monkeypatch.setattr(
            gmail_send_mod, "send", fake_gmail_send
        )

        session = _CapturingSession()
        # 1. Contact lookup
        session.queue(_ScalarOneOrNone(contact))
        # 2. Conversation explicit lookup (None — no conv id passed)
        # 3. Conversation by contact lookup (None — fresh)
        session.queue(_ScalarOneOrNone(None))

        result = await email_adapter.send_email(
            session,
            org_id=_ORG_ID,
            sender_user_id=_USER_ID,
            account_id=account.id,
            contact_id=contact.id,
            subject="Quote for sofa",
            body_text="Hi Mehta, here's your quote",
        )
        assert result.provider_message_id == "gm-msg-xyz"
        assert result.daily_sent_after == 1
        # Conversation + Message rows added.
        types = [type(r).__name__ for r in session.added]
        assert "Conversation" in types
        assert "Message" in types

    @pytest.mark.asyncio
    async def test_hard_cap_surfaces_as_429(self, monkeypatch):
        account = _make_account(provider=EmailAccountProvider.gmail)
        contact = _FakeContact()

        async def fake_get_account(_sess, *, account_id):
            return account

        monkeypatch.setattr(
            "src.app.core.conversations.adapters.email."
            "email_service.get_account",
            fake_get_account,
        )
        from src.app.core.email.gmail import send as gmail_send_mod

        async def fake_send_capped(*_a, **_k):
            raise gmail_send_mod.DailyCapExceeded(sent=500, cap=500)

        monkeypatch.setattr(gmail_send_mod, "send", fake_send_capped)

        session = _CapturingSession()
        session.queue(_ScalarOneOrNone(contact))
        session.queue(_ScalarOneOrNone(None))

        with pytest.raises(email_adapter.HardCapExceeded) as exc:
            await email_adapter.send_email(
                session,
                org_id=_ORG_ID,
                sender_user_id=_USER_ID,
                account_id=account.id,
                contact_id=contact.id,
                subject="x",
                body_text="x",
            )
        assert exc.value.status_code == 429


# --- 5. receive_email flow ----------------------------------------


class _ReceiveSession(_CapturingSession):
    """Mirror of _CapturingSession used as `async_session()` context
    manager target."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def patch_async_session(monkeypatch):
    """Replace `async_session()` with a context yielding our stub."""
    session = _ReceiveSession()

    @asynccontextmanager
    async def fake_async_session():
        yield session

    monkeypatch.setattr(
        "src.app.shared.db.async_session", fake_async_session
    )
    return session


class TestReceiveEmail:
    @pytest.mark.asyncio
    async def test_no_contact_id_drops(self, patch_async_session):
        result = await email_adapter.receive_email(
            _make_account(),
            {"message_id": "x", "headers": {}, "contact_id": None},
        )
        assert result is None
        # No DB writes.
        assert patch_async_session.added == []

    @pytest.mark.asyncio
    async def test_dedupe_by_rfc_id(self, patch_async_session):
        contact_id = uuid.uuid4()
        # Existing row found by rfc id → dedupe returns None.
        patch_async_session.queue(_ScalarOneOrNone(uuid.uuid4()))
        result = await email_adapter.receive_email(
            _make_account(),
            {
                "message_id": "provider-x",
                "headers": {"message-id": "<rfc@x>"},
                "contact_id": contact_id,
            },
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_fresh_conversation_when_no_thread_keys(
        self, patch_async_session
    ):
        contact_id = uuid.uuid4()
        # Dedupe: no existing RFC-id row.
        patch_async_session.queue(_ScalarOneOrNone(None))
        # No provider-id existing.
        patch_async_session.queue(_ScalarOneOrNone(None))
        # Subject-fallback candidate list → empty.
        patch_async_session.queue(_AllRows([]))

        msg = await email_adapter.receive_email(
            _make_account(),
            {
                "message_id": "provider-1",
                "headers": {
                    "message-id": "<m1@example.com>",
                    "subject": "New enquiry",
                    "from": "mehta@designs.com",
                    "to": "asha@yourstore.com",
                },
                "contact_id": contact_id,
                "body_text": "Hi Asha",
            },
        )
        assert isinstance(msg, Message)
        assert msg.direction == MessageDirection.in_
        assert msg.channel_message_id == "m1@example.com"
        # A new Conversation was added alongside the Message.
        types = [type(r).__name__ for r in patch_async_session.added]
        assert "Conversation" in types
        assert "Message" in types

    @pytest.mark.asyncio
    async def test_threads_by_message_id(self, patch_async_session):
        contact_id = uuid.uuid4()
        existing_conv_id = uuid.uuid4()
        existing_conv = Conversation(
            id=existing_conv_id,
            org_id=_ORG_ID,
            channel=ConversationChannel.email,
            external_id="mehta@designs.com",
            contact_id=contact_id,
            status=ConversationStatus.open,
            unread_count=0,
        )
        # Dedupe: no existing RFC-id row.
        patch_async_session.queue(_ScalarOneOrNone(None))
        # No provider-id existing.
        patch_async_session.queue(_ScalarOneOrNone(None))
        # thread-key lookup: prior message exists pointing at the conv.
        prior_msg_row = (existing_conv_id,)
        patch_async_session.queue(_AllRows([prior_msg_row]))
        # Conversation row fetched by id.
        patch_async_session.queue(_ScalarOneOrNone(existing_conv))

        msg = await email_adapter.receive_email(
            _make_account(),
            {
                "message_id": "provider-reply",
                "headers": {
                    "message-id": "<reply@example.com>",
                    "in-reply-to": "<original@yourstore.com>",
                    "subject": "Re: Quote for sofa",
                    "from": "mehta@designs.com",
                    "to": "asha@yourstore.com",
                },
                "contact_id": contact_id,
                "body_text": "Reply body",
            },
        )
        assert msg is not None
        assert msg.conversation_id == existing_conv_id
        # No new Conversation was added — we re-used the existing one.
        types = [type(r).__name__ for r in patch_async_session.added]
        assert types.count("Conversation") == 0
        assert "Message" in types
