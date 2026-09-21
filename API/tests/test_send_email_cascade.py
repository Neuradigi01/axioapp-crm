"""Coverage for Step 5b send cascade in ``conversations/adapters/email.py``.

Exercises the four envelope-kind paths (``oauth_account``,
``smtp_sender``, ``own_domain``, ``platform_from``) end-to-end via
``send_email(...)``, plus the platform-from first-use notification
idempotency and the ``SendNotConfiguredError`` fall-through.

Dispatch is fully monkey-patched — nothing hits SMTP, Gmail, Graph,
or Mailgun. The ``test_db`` fixture is used for real ORM inserts
(org, contact, org_settings, SMTP / OAuth / domain rows) so the
cascade resolver runs against real data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import email as email_adapter
from src.app.core.email.mailgun.api_client import MailgunSendResult
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.settings.models import OrgSettings
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Global patches — every test uses these
# ---------------------------------------------------------------------------


class _FakeMailgun:
    """Stand-in for :class:`MailgunApiClient`.

    Records every ``send_mime`` call so tests can assert on the
    dispatch domain, envelope-to, and full raw MIME (which carries
    the From, Reply-To, tracking headers we want to pin).
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def send_mime(
        self,
        domain: str,
        *,
        to: str,
        raw_mime: bytes,
        tags: list[str] | None = None,
        tracking: bool = True,
    ) -> MailgunSendResult:
        _mailgun_calls.append(
            {
                "domain": domain,
                "to": to,
                "raw_mime": raw_mime,
                "tags": tags,
                "tracking": tracking,
            }
        )
        return MailgunSendResult(mailgun_message_id="mg-fake-123", message="Queued. Thank you.")


_mailgun_calls: list[dict[str, Any]] = []
_gmail_calls: list[dict[str, Any]] = []
_ms_calls: list[dict[str, Any]] = []
_smtp_calls: list[dict[str, Any]] = []
_notify_calls: list[dict[str, Any]] = []


class _FakeGmailResult:
    def __init__(self) -> None:
        self.gmail_message_id = "gmail-fake-id"
        self.daily_sent_after = 1
        self.near_soft_cap = False


class _FakeMsResult:
    def __init__(self) -> None:
        self.provider_message_id = None
        self.daily_sent_after = 1
        self.near_soft_cap = False


class _FakeOrgSmtpBackend:
    def __init__(self, *, sender: EmailSmtpSender) -> None:
        self.sender = sender

    async def send_raw(self, *, raw_bytes: bytes, envelope_from: str, envelope_to: str) -> None:
        _smtp_calls.append(
            {
                "raw_bytes": raw_bytes,
                "envelope_from": envelope_from,
                "envelope_to": envelope_to,
                "sender_id": self.sender.id,
            }
        )


@pytest.fixture(autouse=True)
def _patch_dispatch(monkeypatch):
    """Route every dispatch path to an in-process fake."""
    # Reset shared state.
    _mailgun_calls.clear()
    _gmail_calls.clear()
    _ms_calls.clear()
    _smtp_calls.clear()
    _notify_calls.clear()

    # Mailgun client — the adapter late-imports this from its source
    # module, so patching the source is what routes the call.
    monkeypatch.setattr(
        "src.app.core.email.mailgun.api_client.MailgunApiClient",
        _FakeMailgun,
    )

    # OAuth Gmail send.
    async def _fake_gmail_send(account, session, *, raw_mime):
        _gmail_calls.append({"account_id": account.id, "raw_mime": raw_mime})
        return _FakeGmailResult()

    monkeypatch.setattr(
        "src.app.core.email.gmail.send.send",
        _fake_gmail_send,
    )
    # Legacy alias that some send paths might reach via.
    monkeypatch.setattr(
        "src.app.core.email.gmail.send.DEFAULT_HARD_CAP",
        1000,
        raising=False,
    )

    # OAuth Microsoft send.
    async def _fake_ms_send(account, session, *, raw_mime):
        _ms_calls.append({"account_id": account.id, "raw_mime": raw_mime})
        return _FakeMsResult()

    monkeypatch.setattr(
        "src.app.core.email.microsoft.send.send",
        _fake_ms_send,
    )
    monkeypatch.setattr(
        "src.app.core.email.microsoft.send.DEFAULT_HARD_CAP",
        1000,
        raising=False,
    )

    # SMTP backend.
    monkeypatch.setattr(
        "src.app.shared.email.org_sender.OrgSmtpBackend",
        _FakeOrgSmtpBackend,
    )

    # External IO — these open their own sessions in prod; here we
    # neuter them so nothing tries to hit the shared DB.
    async def _noop_activity(*_a, **_k):
        return None

    monkeypatch.setattr(email_adapter, "activities_log", _noop_activity)
    monkeypatch.setattr(email_adapter.audit, "log", _noop_activity)

    async def _capture_notify(**kwargs):
        _notify_calls.append(kwargs)

    monkeypatch.setattr(
        "src.app.core.notifications.service.notify",
        _capture_notify,
    )


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_org(session, name: str = "Cascade Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"c-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    session.add(
        OrgSettings(
            org_id=org.id,
            address_line1="123 CAN-SPAM Compliance Way",
            city="Test City",
        )
    )
    await session.flush()
    return org


async def _seed_contact(session, *, org_id: uuid.UUID) -> Contact:
    contact = Contact(
        org_id=org_id,
        full_name="Test Recipient",
        email=f"rcpt-{uuid.uuid4().hex[:6]}@customer.example",
        email_opt_out=False,
    )
    session.add(contact)
    await session.flush()
    return contact


async def _seed_smtp_sender(
    session,
    *,
    org_id: uuid.UUID,
    is_default: bool = True,
    verified: bool = True,
) -> EmailSmtpSender:
    sender = EmailSmtpSender(
        org_id=org_id,
        from_address=f"send-{uuid.uuid4().hex[:6]}@example.com",
        display_name="Sales",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user",
        smtp_password_enc="ct",
        tls_mode="starttls",
        verified_at=datetime.now(UTC) if verified else None,
        is_default=is_default,
        inbound_token=uuid.uuid4().hex[:12],
        capture_replies_in_crm=False,  # Keep raw_mime Reply-To untouched.
    )
    session.add(sender)
    await session.flush()
    return sender


async def _seed_oauth_account(
    session,
    *,
    org_id: uuid.UUID,
    is_default: bool = True,
    provider: EmailAccountProvider = EmailAccountProvider.gmail,
) -> EmailAccount:
    account = EmailAccount(
        org_id=org_id,
        user_id=uuid.uuid4(),
        provider=provider,
        external_account_id=f"ext-{uuid.uuid4().hex[:8]}",
        email_address=f"rep-{uuid.uuid4().hex[:6]}@company.example",
        display_name="Rep",
        access_token_enc="a",
        refresh_token_enc="r",
        sync_state=EmailAccountSyncState.live,
        is_default=is_default,
    )
    session.add(account)
    await session.flush()
    return account


async def _seed_verified_domain(
    session,
    *,
    org_id: uuid.UUID,
    domain: str,
) -> OrganizationEmailDomain:
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id="mg-domain-id",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_demoted_domain(
    session,
    *,
    org_id: uuid.UUID,
    domain: str,
) -> OrganizationEmailDomain:
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id="mg-domain-id-demoted",
        dns_records={},
        verification_status=VERIFICATION_STATUS_DEMOTED,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# 1. Caller-supplied short-circuits — cascade NOT consulted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_caller_supplied_smtp_short_circuits(test_db):
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    sender = await _seed_smtp_sender(test_db, org_id=org.id, is_default=False, verified=True)
    # Seed a verified own-domain that the cascade WOULD pick if consulted.
    await _seed_verified_domain(test_db, org_id=org.id, domain="ignored.example")
    await test_db.commit()

    result = await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        smtp_sender_id=sender.id,
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    # SMTP path fired, Mailgun did NOT.
    assert len(_smtp_calls) == 1
    assert _smtp_calls[0]["sender_id"] == sender.id
    assert _mailgun_calls == []
    # Persisted message carries the SMTP provider label.
    assert result.message.payload["provider"] == "smtp"


@pytest.mark.asyncio
async def test_send_cascade_caller_supplied_oauth_short_circuits(test_db):
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    account = await _seed_oauth_account(test_db, org_id=org.id, is_default=False)
    # Verified domain the cascade WOULD pick if consulted.
    await _seed_verified_domain(test_db, org_id=org.id, domain="ignored.example")
    await test_db.commit()

    result = await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        account_id=account.id,
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    assert len(_gmail_calls) == 1
    assert _gmail_calls[0]["account_id"] == account.id
    assert _mailgun_calls == []
    assert result.message.payload["provider"] == "gmail"


# ---------------------------------------------------------------------------
# 2. Cascade → own_domain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_falls_to_own_domain_when_no_caller_supplied(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    domain_row = await _seed_verified_domain(test_db, org_id=org.id, domain="ownedby.example")
    await test_db.commit()

    result = await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    assert len(_mailgun_calls) == 1
    call = _mailgun_calls[0]
    assert call["domain"] == "ownedby.example"
    assert call["to"] == contact.email
    assert result.message.payload["provider"] == "mailgun_own_domain"
    # own_domain envelope's from is ``no-reply@<domain>``.
    assert b"From: no-reply@ownedby.example" in call["raw_mime"]
    # Sanity: domain row referenced by the envelope came from Mailgun-managed table.
    assert domain_row.verification_status == VERIFICATION_STATUS_VERIFIED


# ---------------------------------------------------------------------------
# 3. Cascade → platform_from
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_falls_to_platform_from_when_no_own_domain(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    result = await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    assert len(_mailgun_calls) == 1
    call = _mailgun_calls[0]
    assert call["domain"] == "platform.example"
    assert result.message.payload["provider"] == "mailgun_platform_from"


@pytest.mark.asyncio
async def test_send_cascade_platform_from_uses_org_uuid_local_part(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    raw = _mailgun_calls[0]["raw_mime"]
    expected_from = f"From: org-{org.id}@platform.example".encode()
    assert expected_from in raw


@pytest.mark.asyncio
async def test_send_cascade_platform_from_reply_to_uses_r_token(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    raw = _mailgun_calls[0]["raw_mime"]
    # ``Reply-To: r-<token>@reply.platform.example`` — regex match on
    # the r-<12chars>@<inbound-domain> shape.
    import re

    match = re.search(rb"Reply-To: r-([A-Za-z0-9_-]+)@reply\.platform\.example", raw)
    assert match is not None, raw.decode("utf-8", errors="replace")


@pytest.mark.asyncio
async def test_send_cascade_platform_from_creates_endpoint_row_on_first_use(test_db, monkeypatch):
    from src.app.core.channel_endpoints.models import (
        ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
        ChannelEndpoint,
    )

    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    # Precondition: no platform reply-capture endpoint for this org.
    existing = (
        await test_db.execute(
            select(ChannelEndpoint).where(
                ChannelEndpoint.org_id == org.id,
                ChannelEndpoint.endpoint_type == ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
            )
        )
    ).all()
    assert existing == []

    await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )

    created = (
        await test_db.execute(
            select(ChannelEndpoint).where(
                ChannelEndpoint.org_id == org.id,
                ChannelEndpoint.endpoint_type == ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
            )
        )
    ).all()
    assert len(created) == 1


@pytest.mark.asyncio
async def test_send_cascade_first_platform_from_notification_idempotent(test_db, monkeypatch):
    """The endpoint-created gate ensures the first-use notification
    helper fires exactly once. Send #1 mints a fresh reply-capture
    endpoint → gate enters → helper runs. Send #2 reuses that endpoint
    → ``endpoint_created_this_call=False`` → gate short-circuits, helper
    skipped entirely.

    Tests the OUTER gate (the ``if endpoint_created_this_call and ...``
    branch). The INNER
    :func:`already_notified_first_platform_from` DB check is covered
    directly in :mod:`test_email_platform_from`.
    """
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    # Wrap the helper so we can count invocations without stubbing
    # its (harmless) real behaviour.
    call_count = {"n": 0}
    original_helper = email_adapter._notify_first_platform_from_send

    async def _counting(session, *, org_id):
        call_count["n"] += 1
        await original_helper(session, org_id=org_id)

    monkeypatch.setattr(email_adapter, "_notify_first_platform_from_send", _counting)

    # First platform-from send — mints the endpoint → helper fires.
    await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="First",
        body_text="hi",
    )
    assert call_count["n"] == 1

    # Second platform-from send — endpoint now exists, gate short-
    # circuits, helper is NOT called again.
    await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Second",
        body_text="hi",
    )
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# 4. Demoted own-domain is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_skips_demoted_own_domain(test_db, monkeypatch):
    """A demoted domain must not win the cascade — send falls through
    to platform_from."""
    monkeypatch.setenv("EMAIL_PLATFORM_SENDING_DOMAIN", "platform.example")
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "reply.platform.example")
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await _seed_demoted_domain(test_db, org_id=org.id, domain="drift.example")
    await test_db.commit()

    result = await email_adapter.send_email(
        test_db,
        org_id=org.id,
        sender_user_id=uuid.uuid4(),
        contact_id=contact.id,
        subject="Hello",
        body_text="hi",
    )
    # Envelope resolved to platform_from, not own_domain.
    assert result.message.payload["provider"] == "mailgun_platform_from"
    assert _mailgun_calls[0]["domain"] == "platform.example"


# ---------------------------------------------------------------------------
# 5. All paths miss → SendNotConfigured surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_raises_send_not_configured_when_all_paths_miss(test_db, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("EMAIL_PLATFORM_SENDING_DOMAIN", raising=False)
    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await email_adapter.send_email(
            test_db,
            org_id=org.id,
            sender_user_id=uuid.uuid4(),
            contact_id=contact.id,
            subject="Hello",
            body_text="hi",
        )
    assert exc_info.value.status_code == 400
    assert "No sending path is configured" in exc_info.value.detail
    # Neither Mailgun nor OAuth nor SMTP dispatch fired.
    assert _mailgun_calls == []
    assert _gmail_calls == []
    assert _smtp_calls == []


# ---------------------------------------------------------------------------
# 6. Both-supplied guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_cascade_both_ids_supplied_returns_400(test_db):
    """Regression pin: supplying BOTH ``account_id`` and
    ``smtp_sender_id`` still 400s. The relaxed guard only widened
    "at most one" — both-supplied is still an obvious caller bug."""
    from fastapi import HTTPException

    org = await _seed_org(test_db)
    contact = await _seed_contact(test_db, org_id=org.id)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await email_adapter.send_email(
            test_db,
            org_id=org.id,
            sender_user_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            smtp_sender_id=uuid.uuid4(),
            contact_id=contact.id,
            subject="Hello",
            body_text="hi",
        )
    assert exc_info.value.status_code == 400
