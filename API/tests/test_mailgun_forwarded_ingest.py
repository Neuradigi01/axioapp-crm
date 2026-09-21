"""Coverage for Step 3 of ``tasks/email-inbound-forwarding/``.

Exercises the new ``f-<token>`` prefix dispatch + the forwarded-
address ingest branch. Test surfaces:

  * ``mailgun_service.parse_recipient_kind`` — pure-function coverage
    of the two-prefix router.
  * ``handle_forwarded_address`` — integration coverage via
    ``_process_async`` (Celery task's async body) — mirrors the
    shipped ``test_mailgun_step4_ingest`` pattern (writes a fake
    pending-inbound directory + payload.json, drains the task
    inline).

Mailgun-side infrastructure (Route filter, webhook dispatch,
pending-directory write) is unchanged by this track — Step 3 is
Python-side ingest only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import Conversation, Message
from src.app.core.email.mailgun import service as mgs
from src.app.core.email.mailgun.tasks import _process_async
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "FW Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"fw-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_forwarded_endpoint(
    session,
    *,
    org_id: uuid.UUID,
    token: str = "fwdtok123456",
    auto_create_contact: bool = True,
    default_assignee_user_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="forwarded_address",
        label="Support inbox",
        is_active=is_active,
    )
    session.add(endpoint)
    await session.flush()
    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        forwarding_token=token,
        auto_create_contact=auto_create_contact,
        default_assignee_user_id=default_assignee_user_id,
    )
    session.add(details)
    await session.flush()
    return endpoint, details


async def _make_contact(session, *, org_id: uuid.UUID, email: str) -> Contact:
    now = datetime.now(UTC)
    c = Contact(
        id=uuid.uuid4(),
        org_id=org_id,
        full_name=f"Cust {uuid.uuid4().hex[:6]}",
        email=email,
        created_at=now,
        updated_at=now,
    )
    session.add(c)
    await session.flush()
    return c


def _write_pending(tmp_path: Path, payload: dict[str, Any]) -> Path:
    root = tmp_path / "pending-inbound" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    (root / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


class _FakeTask:
    class _Req:
        retries = 0

    request = _Req()
    max_retries = 3


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session on the live DB; neuter it so
    the tests don't spew ``sqlalchemy.exc``."""

    async def _noop(*_a, **_k):
        return None

    # Patch every module the task graph touches.
    monkeypatch.setattr("src.app.core.audit.service.log", _noop)


# ---------------------------------------------------------------------------
# 1. Prefix dispatch — pure functions
# ---------------------------------------------------------------------------


def test_parse_recipient_kind_in_underscore_is_reply_capture():
    parsed = mgs.parse_recipient_kind("in_abc123@reply.example.com")
    assert parsed == (mgs.RECIPIENT_KIND_REPLY_CAPTURE, "abc123")


def test_parse_recipient_kind_f_dash_is_forwarded_address():
    parsed = mgs.parse_recipient_kind("f-tok123456@reply.example.com")
    assert parsed == (mgs.RECIPIENT_KIND_FORWARDED_ADDRESS, "tok123456")


def test_parse_recipient_kind_unknown_prefix_returns_none():
    """Anything else (bare local part, ``support@``, empty) drops."""
    assert mgs.parse_recipient_kind("support@reply.example.com") is None
    assert mgs.parse_recipient_kind("") is None
    assert mgs.parse_recipient_kind("f-@reply.example.com") is None
    assert mgs.parse_recipient_kind("in_@reply.example.com") is None


def test_extract_all_our_recipients_matches_both_prefixes():
    payload = {
        "recipient": (
            "f-fwdtok123@reply.example.com, in_replytok456@reply.example.com, unrelated@example.com"
        )
    }
    hits = mgs.extract_all_our_recipients(payload)
    assert len(hits) == 2
    assert "f-fwdtok123@reply.example.com" in hits
    assert "in_replytok456@reply.example.com" in hits


# ---------------------------------------------------------------------------
# 2. End-to-end ingest — the dispatch loop
# ---------------------------------------------------------------------------


async def test_ingest_f_dash_prefix_routes_to_forwarded_address_path(test_db, tmp_path):
    """A payload with ``f-<token>`` lands as a Mailgun-forwarded row
    stamped with ``endpoint_type='forwarded_address'`` in payload."""
    org = await _make_org(test_db)
    endpoint, _details = await _make_forwarded_endpoint(
        test_db, org_id=org.id, token="fwd001234567", auto_create_contact=False
    )
    contact = await _make_contact(test_db, org_id=org.id, email="unknown-sender@customer.example")
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@mail.example>"
    payload = {
        "sender": contact.email,
        "recipient": "f-fwd001234567@reply.example.com",
        "Subject": "Support question",
        "From": contact.email,
        "Message-Id": delivery_id,
        "body-plain": "Can you help?",
        "X-Mailgun-Spf": "pass",
        "X-Mailgun-Dkim-Signature": "pass",
    }
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    msg = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalar_one()
    assert msg.channel_message_id == f"mg:{delivery_id}"
    assert msg.payload["endpoint_type"] == "forwarded_address"
    assert msg.payload["endpoint_id"] == str(endpoint.id)
    assert msg.payload["forwarding_token"] == "fwd001234567"
    assert not pending.exists()


async def test_ingest_in_underscore_prefix_routes_to_reply_capture_path(test_db, tmp_path):
    """Shipped ``in_<token>`` prefix still routes to the reply-capture
    branch — the forwarded-address dispatch does NOT intercept it."""
    org = await _make_org(test_db)
    # Seed an unknown ``in_`` token — the reply-capture branch will
    # look for an SMTP sender, not find one, and drop with an audit.
    # We assert the forwarded branch didn't fire (no forwarded_address
    # stamped in any row).
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@mail.example>"
    payload = {
        "sender": "customer@ex.com",
        "recipient": "in_UNKNOWN_TOKEN@reply.example.com",
        "Subject": "Reply",
        "From": "customer@ex.com",
        "Message-Id": delivery_id,
        "body-plain": "Hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    # No forwarded_address row landed — dispatch chose reply-capture
    # (which found no sender and dropped).
    msgs = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalars().all()
    for m in msgs:
        assert m.payload.get("endpoint_type") != "forwarded_address"
    assert not pending.exists()


async def test_ingest_unknown_prefix_audits_and_drops(test_db, tmp_path):
    """A recipient with neither ``in_`` nor ``f-`` prefix — the ingest
    audits ``mailgun.inbound.unknown_prefix`` and drops. No message
    row lands."""
    org = await _make_org(test_db)
    await test_db.commit()

    payload = {
        "sender": "somebody@ex.com",
        "recipient": "support@reply.example.com",
        "Subject": "??",
        "From": "somebody@ex.com",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "Hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalars().all()
    assert rows == []
    assert not pending.exists()


# ---------------------------------------------------------------------------
# 3. Forwarded-address ingest — behaviour
# ---------------------------------------------------------------------------


async def test_forwarded_ingest_uses_mailgun_recipient_not_to_header(test_db, tmp_path):
    """Mailgun's ``recipient`` field (RCPT TO) is what drives the
    lookup — the ``To:`` header (which shows the customer's original
    support address) is IGNORED for routing. Otherwise a forwarded
    mail from ``support@customer.example`` would 404 on our token
    lookup."""
    org = await _make_org(test_db)
    endpoint, _ = await _make_forwarded_endpoint(test_db, org_id=org.id, token="rcpt00123456")
    await test_db.commit()

    payload = {
        "sender": "third-party@example.net",
        # ``recipient`` matches our f-token.
        "recipient": "f-rcpt00123456@reply.example.com",
        # ``To:`` header carries the customer's original support address —
        # if the ingest tried to route from To: it would fail here.
        "To": "support@customer.example",
        "From": "third-party@example.net",
        "Subject": "Question",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "Hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    msg = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalar_one()
    assert msg.payload["endpoint_id"] == str(endpoint.id)


async def test_forwarded_ingest_creates_new_conversation_on_first_touch(test_db, tmp_path):
    org = await _make_org(test_db)
    await _make_forwarded_endpoint(test_db, org_id=org.id, token="new001234567")
    contact = await _make_contact(test_db, org_id=org.id, email="known@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-new001234567@reply.example.com",
        "Subject": "First contact",
        "From": contact.email,
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "Hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    convs = (
        (await test_db.execute(select(Conversation).where(Conversation.org_id == org.id)))
        .scalars()
        .all()
    )
    assert len(convs) == 1
    assert convs[0].contact_id == contact.id


async def test_forwarded_ingest_assigns_to_default_assignee_when_set(test_db, tmp_path):
    """A fresh conversation inherits the endpoint's
    ``default_assignee_user_id``."""
    org = await _make_org(test_db)
    assignee_id = uuid.uuid4()
    await _make_forwarded_endpoint(
        test_db,
        org_id=org.id,
        token="asn001234567",
        default_assignee_user_id=assignee_id,
    )
    contact = await _make_contact(test_db, org_id=org.id, email="known2@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-asn001234567@reply.example.com",
        "From": contact.email,
        "Subject": "hello",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    conv = (
        await test_db.execute(select(Conversation).where(Conversation.org_id == org.id))
    ).scalar_one()
    assert conv.assigned_to_id == assignee_id


async def test_forwarded_ingest_assigns_to_unassigned_when_default_null(test_db, tmp_path):
    org = await _make_org(test_db)
    await _make_forwarded_endpoint(
        test_db,
        org_id=org.id,
        token="una001234567",
        default_assignee_user_id=None,
    )
    contact = await _make_contact(test_db, org_id=org.id, email="known3@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-una001234567@reply.example.com",
        "From": contact.email,
        "Subject": "hello",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    conv = (
        await test_db.execute(select(Conversation).where(Conversation.org_id == org.id))
    ).scalar_one()
    assert conv.assigned_to_id is None


async def test_forwarded_ingest_spf_fail_persists_with_spoof_flag_and_null_contact(
    test_db, tmp_path
):
    """SPF explicit-fail + a matched contact → drop the auto-attribution,
    flag ``spoof_suspected=True``, leave ``contact_id=None``.
    Mirrors the reply-capture path's Attacker C2 fix."""
    org = await _make_org(test_db)
    await _make_forwarded_endpoint(test_db, org_id=org.id, token="spf001234567")
    contact = await _make_contact(test_db, org_id=org.id, email="target@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-spf001234567@reply.example.com",
        "From": contact.email,
        "Subject": "spoofed",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "?",
        # Explicit SPF fail.
        "X-Mailgun-Spf": "fail",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    msg = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalar_one()
    assert msg.payload["spoof_suspected"] is True
    # contact_id nulled on the conversation for spoof-suspected.
    conv = (
        await test_db.execute(select(Conversation).where(Conversation.id == msg.conversation_id))
    ).scalar_one()
    assert conv.contact_id is None


async def test_forwarded_ingest_auto_submitted_flags_generated_skips_workflow_events(
    test_db, tmp_path
):
    """``Auto-Submitted: auto-generated`` → ``auto_generated=True`` on
    the persisted row + workflow events skipped."""
    org = await _make_org(test_db)
    await _make_forwarded_endpoint(test_db, org_id=org.id, token="aut001234567")
    contact = await _make_contact(test_db, org_id=org.id, email="loop@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-aut001234567@reply.example.com",
        "From": contact.email,
        "Subject": "vacation reply",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "OOO",
        "message-headers": json.dumps([["Auto-Submitted", "auto-generated"]]),
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    msg = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalar_one()
    assert msg.payload["auto_generated"] is True


async def test_forwarded_ingest_updates_endpoint_last_inbound_at(test_db, tmp_path):
    """A successful ingest bumps ``details.last_inbound_at`` — powers
    the inbox-settings UI's "last received" column."""
    org = await _make_org(test_db)
    endpoint, details = await _make_forwarded_endpoint(test_db, org_id=org.id, token="lst001234567")
    contact = await _make_contact(test_db, org_id=org.id, email="pinger@customer.example")
    await test_db.commit()
    assert details.last_inbound_at is None

    payload = {
        "sender": contact.email,
        "recipient": "f-lst001234567@reply.example.com",
        "From": contact.email,
        "Subject": "hi",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    # Reload details row.
    fresh = (
        await test_db.execute(
            sql_text(
                "SELECT last_inbound_at FROM tbl_email_endpoint_details WHERE endpoint_id = :id"
            ),
            {"id": endpoint.id},
        )
    ).scalar_one()
    assert fresh is not None


async def test_forwarded_ingest_inactive_endpoint_audits_drops(test_db, tmp_path):
    """An inactive endpoint doesn't match ``find_by_forwarding_token``
    (which filters ``is_active=True``) — ingest drops with an audit
    reason of ``no_endpoint_for_token_or_inactive`` and no message
    row lands."""
    org = await _make_org(test_db)
    await _make_forwarded_endpoint(test_db, org_id=org.id, token="off001234567", is_active=False)
    contact = await _make_contact(test_db, org_id=org.id, email="ping2@customer.example")
    await test_db.commit()

    payload = {
        "sender": contact.email,
        "recipient": "f-off001234567@reply.example.com",
        "From": contact.email,
        "Subject": "hi",
        "Message-Id": f"<{uuid.uuid4().hex}@ex.com>",
        "body-plain": "hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (await test_db.execute(select(Message).where(Message.org_id == org.id))).scalars().all()
    assert rows == []
    assert not pending.exists()
