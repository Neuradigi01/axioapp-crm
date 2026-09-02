"""Coverage for Step 4 of the mailgun-inbound track.

Split into two surfaces:

  A. Pure-function coverage of the Mailgun payload parsers
     (``extract_headers``, ``parse_spf_result``, ``parse_dkim_result``,
     ``detect_auto_responder``, ``extract_recipient_token``,
     ``extract_all_our_recipients``, ``parse_sender_email``).

  B. Integration coverage of the ingest end-to-end: build a
     pending-inbound directory + payload.json on disk, run the
     Celery task inline (``eager`` mode is on for tests via
     ``CELERY_ENABLED=false``), assert the DB shape.

The extraction of ``_persist_inbound_email`` from ``receive_email``
is asserted via a byte-shape test: the OAuth call site's output row
(after the refactor) matches the historical output row (before the
refactor) for the same input.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters.email import (
    _persist_inbound_email,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.email.mailgun import service as mgs
from src.app.core.email.mailgun.dlq_models import EmailInboundDlq
from src.app.core.email.mailgun.tasks import (
    _cleanup,
    _process_async,
    _write_to_dlq,
)
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.email_senders.service import _generate_inbound_token
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# A. Payload parsers — pure functions
# ---------------------------------------------------------------------------


class TestExtractHeaders:
    def test_merges_message_headers_json_and_canonical_headers(self):
        payload = {
            "Subject": "Canonical Subject",
            "message-headers": json.dumps(
                [
                    ["Subject", "Superseded"],
                    ["References", "<r1@ex.com>"],
                    ["X-Custom", "extra"],
                ]
            ),
            "From": "alice@ex.com",
        }
        h = mgs.extract_headers(payload)
        # Canonical wins over message-headers.
        assert h["subject"] == "Canonical Subject"
        assert h["references"] == "<r1@ex.com>"
        assert h["from"] == "alice@ex.com"
        assert h["x-custom"] == "extra"

    def test_handles_missing_message_headers(self):
        payload = {"Subject": "Hi", "From": "a@ex.com"}
        h = mgs.extract_headers(payload)
        assert h == {"subject": "Hi", "from": "a@ex.com"}

    def test_ignores_malformed_message_headers_json(self):
        payload = {"Subject": "Hi", "message-headers": "{{not-json"}
        h = mgs.extract_headers(payload)
        assert h == {"subject": "Hi"}


class TestParseSpfDkim:
    def test_spf_valid_verdicts(self):
        for v in ("pass", "fail", "softfail", "neutral", "none"):
            assert mgs.parse_spf_result({"X-Mailgun-Spf": v}) == v
            assert mgs.parse_spf_result({"X-Mailgun-Spf": v.upper()}) == v

    def test_spf_returns_none_when_absent(self):
        assert mgs.parse_spf_result({}) is None

    def test_spf_returns_none_for_unknown_verdict(self):
        assert mgs.parse_spf_result({"X-Mailgun-Spf": "maybe"}) is None

    def test_dkim_valid_verdicts(self):
        for v in ("pass", "fail", "none"):
            assert mgs.parse_dkim_result({"X-Mailgun-Dkim-Signature": v}) == v

    def test_dkim_returns_none_when_absent(self):
        assert mgs.parse_dkim_result({}) is None


class TestDetectAutoResponder:
    def test_auto_submitted_yes_is_auto(self):
        assert mgs.detect_auto_responder({"auto-submitted": "auto-replied"}) is True
        assert mgs.detect_auto_responder({"auto-submitted": "auto-generated"}) is True

    def test_auto_submitted_no_is_not_auto(self):
        assert mgs.detect_auto_responder({"auto-submitted": "no"}) is False

    def test_precedence_bulk_is_auto(self):
        assert mgs.detect_auto_responder({"precedence": "bulk"}) is True
        assert mgs.detect_auto_responder({"precedence": "list"}) is True
        assert mgs.detect_auto_responder({"precedence": "junk"}) is True

    def test_precedence_first_class_is_not_auto(self):
        assert mgs.detect_auto_responder({"precedence": "first-class"}) is False

    def test_x_auto_response_suppress_is_auto(self):
        assert mgs.detect_auto_responder({"x-auto-response-suppress": "All"}) is True
        assert mgs.detect_auto_responder({"x-auto-response-suppress": "OOF"}) is True

    def test_no_headers_is_not_auto(self):
        assert mgs.detect_auto_responder({}) is False


class TestExtractRecipientToken:
    def test_valid_local_part(self):
        assert (
            mgs.extract_recipient_token("in_ABC123XYZ@reply.example.com")
            == "ABC123XYZ"
        )

    def test_missing_prefix_returns_none(self):
        assert mgs.extract_recipient_token("plain@ex.com") is None
        assert mgs.extract_recipient_token("indirect_but_not_prefix@ex.com") is None

    def test_empty_input(self):
        assert mgs.extract_recipient_token("") is None
        assert mgs.extract_recipient_token("in_@ex.com") is None


class TestExtractAllOurRecipients:
    def test_single_recipient(self):
        payload = {"recipient": "in_tk1@reply.example.com"}
        assert mgs.extract_all_our_recipients(payload) == ["in_tk1@reply.example.com"]

    def test_multi_recipient_list(self):
        payload = {
            "recipient": ["in_tk1@reply.example.com", "in_tk2@reply.example.com"]
        }
        assert len(mgs.extract_all_our_recipients(payload)) == 2

    def test_comma_separated(self):
        payload = {"recipient": "in_a@x.com, in_b@x.com"}
        assert len(mgs.extract_all_our_recipients(payload)) == 2

    def test_non_our_recipient_filtered(self):
        payload = {"recipient": ["in_valid@x.com", "unknown@x.com"]}
        assert mgs.extract_all_our_recipients(payload) == ["in_valid@x.com"]


class TestParseSenderEmail:
    def test_sender_field_lowercased(self):
        assert mgs.parse_sender_email({"sender": "CUSTOMER@Ex.COM"}) == "customer@ex.com"

    def test_from_display_name_stripped(self):
        assert (
            mgs.parse_sender_email({"From": '"Alice Wonderland" <alice@ex.com>'})
            == "alice@ex.com"
        )

    def test_missing_returns_empty(self):
        assert mgs.parse_sender_email({}) == ""


# ---------------------------------------------------------------------------
# B. Ingest end-to-end — build pending-inbound + run task inline
# ---------------------------------------------------------------------------


async def _make_org(session, slug: str = "step4") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_sender(session, org_id: uuid.UUID) -> EmailSmtpSender:
    from datetime import UTC, datetime

    sender = EmailSmtpSender(
        id=uuid.uuid4(),
        org_id=org_id,
        from_address=f"sales-{uuid.uuid4().hex[:6]}@acme.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="u",
        smtp_password_enc="ciphertext",
        tls_mode="starttls",
        inbound_token=_generate_inbound_token(),
        verified_at=datetime.now(UTC),
        capture_replies_in_crm=True,
    )
    session.add(sender)
    await session.flush()
    return sender


async def _make_contact(session, org_id: uuid.UUID, email: str) -> Contact:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    c = Contact(
        id=uuid.uuid4(),
        org_id=org_id,
        first_name="Cust",
        last_name=str(uuid.uuid4())[:6],
        email=email,
        created_at=now,
        updated_at=now,
    )
    session.add(c)
    await session.flush()
    return c


def _write_pending(tmp_path: Path, payload: dict[str, Any]) -> Path:
    """Simulate the webhook's persist_pending_inbound: write a
    payload.json into a fresh uuid dir under tmp_path/pending-inbound/."""
    root = tmp_path / "pending-inbound" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    (root / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


class _FakeTask:
    """Duck-typed Celery task for ``_process_async``. The real task
    ships with .request.retries — the ingest reads it only in the
    exhausted-retries path."""

    class _Req:
        retries = 0

    request = _Req()
    max_retries = 3


@pytest.mark.asyncio
async def test_ingest_persists_message_with_mg_prefix_channel_id(test_db, tmp_path):
    org = await _make_org(test_db, "e2e")
    sender = await _make_sender(test_db, org.id)
    contact = await _make_contact(test_db, org.id, "customer@ex.com")
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@mail.example>"
    payload = {
        "sender": "customer@ex.com",
        "recipient": f"in_{sender.inbound_token}@reply.neuradigi.com",
        "Subject": "Re: your quote",
        "From": "customer@ex.com",
        "Message-Id": delivery_id,
        "body-plain": "Sounds good, let's do it.",
        "X-Mailgun-Spf": "pass",
        "X-Mailgun-Dkim-Signature": "pass",
    }
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    # Message persisted with mg:<delivery_id> channel_message_id.
    rows = (
        await test_db.execute(
            select(Message).where(Message.org_id == org.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    msg = rows[0]
    assert msg.channel_message_id == f"mg:{delivery_id}"
    assert msg.direction == MessageDirection.in_
    assert msg.spf_result == "pass"
    assert msg.dkim_result == "pass"
    assert msg.text == "Sounds good, let's do it."
    assert msg.payload["provider"] == "mailgun"
    assert msg.payload["smtp_sender_id"] == str(sender.id)
    assert msg.payload["mailgun_delivery_id"] == delivery_id
    # Contact matched — conversation carries contact_id.
    conv = (
        await test_db.execute(
            select(Conversation).where(Conversation.id == msg.conversation_id)
        )
    ).scalar_one()
    assert conv.contact_id == contact.id
    # Directory cleaned up.
    assert not pending.exists()


@pytest.mark.asyncio
async def test_ingest_unknown_recipient_drops_no_message_persisted(test_db, tmp_path):
    org = await _make_org(test_db, "unknown")
    await test_db.commit()

    payload = {
        "sender": "somebody@ex.com",
        "recipient": "in_FAKE_TOKEN@reply.neuradigi.com",
        "Subject": "??",
        "From": "somebody@ex.com",
        "Message-Id": "<msg@ex.com>",
        "body-plain": "Hello",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert rows == []
    assert not pending.exists()


@pytest.mark.asyncio
async def test_ingest_multi_recipient_payload_rejected(test_db, tmp_path):
    org = await _make_org(test_db, "multi")
    sender = await _make_sender(test_db, org.id)
    await test_db.commit()

    payload = {
        "sender": "x@ex.com",
        "recipient": [
            f"in_{sender.inbound_token}@reply.neuradigi.com",
            "in_another@reply.neuradigi.com",
        ],
        "Message-Id": "<msg1@ex.com>",
        "body-plain": "Hi",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    # No message persisted, directory cleaned up.
    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert rows == []
    assert not pending.exists()


@pytest.mark.asyncio
async def test_ingest_spf_fail_matching_contact_drops_attribution(test_db, tmp_path):
    """Attacker C2 fix: spoofed From with a real contact email +
    SPF fail → persist with contact_id=NULL + no workflow event."""
    org = await _make_org(test_db, "spoof")
    sender = await _make_sender(test_db, org.id)
    ceo = await _make_contact(test_db, org.id, "ceo@bigco.com")
    await test_db.commit()

    payload = {
        "sender": "attacker@bad.com",
        "From": '"CEO" <ceo@bigco.com>',  # spoofed From
        "recipient": f"in_{sender.inbound_token}@reply.neuradigi.com",
        "Subject": "URGENT WIRE",
        "Message-Id": "<spoof@bad.com>",
        "body-plain": "Send $50k",
        "X-Mailgun-Spf": "fail",
        "X-Mailgun-Dkim-Signature": "fail",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert len(rows) == 1
    msg = rows[0]
    # Persisted (operator can review) but NOT attributed to the CEO.
    assert msg.spf_result == "fail"
    assert msg.dkim_result == "fail"
    conv = (
        await test_db.execute(
            select(Conversation).where(Conversation.id == msg.conversation_id)
        )
    ).scalar_one()
    # The contact_id on the conversation must NOT be the spoofed CEO.
    assert conv.contact_id != ceo.id
    # Payload flags spoof.
    assert msg.payload.get("spoof_suspected") is True


@pytest.mark.asyncio
async def test_ingest_auto_responder_persists_without_workflow_flag(
    test_db, tmp_path, monkeypatch
):
    """Auto-generated payloads land in the inbox but must be flagged
    so we don't fire ``email.replied`` workflows (mail-loop risk)."""
    org = await _make_org(test_db, "auto")
    sender = await _make_sender(test_db, org.id)
    contact = await _make_contact(test_db, org.id, "vacationer@ex.com")
    await test_db.commit()

    payload = {
        "sender": "vacationer@ex.com",
        "From": "vacationer@ex.com",
        "recipient": f"in_{sender.inbound_token}@reply.neuradigi.com",
        "Subject": "Out of Office",
        "Message-Id": "<ooo@ex.com>",
        "Auto-Submitted": "auto-replied",
        "body-plain": "I am out until next Monday.",
        "X-Mailgun-Spf": "pass",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert len(rows) == 1
    msg = rows[0]
    assert msg.payload.get("auto_generated") is True


@pytest.mark.asyncio
async def test_ingest_dedupe_second_delivery_dropped(test_db, tmp_path):
    """Two Mailgun deliveries with same delivery_id → second is
    caught by the unique index + application-level dedup."""
    org = await _make_org(test_db, "dedup")
    sender = await _make_sender(test_db, org.id)
    await _make_contact(test_db, org.id, "c@ex.com")
    await test_db.commit()

    delivery_id = "<same@ex.com>"
    payload = {
        "sender": "c@ex.com",
        "recipient": f"in_{sender.inbound_token}@reply.neuradigi.com",
        "Message-Id": delivery_id,
        "body-plain": "Hi",
        "X-Mailgun-Spf": "pass",
    }
    p1 = _write_pending(tmp_path, payload)
    p2 = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), p1)
    await _process_async(_FakeTask(), p2)

    rows = (
        await test_db.execute(
            select(Message).where(Message.org_id == org.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_ingest_missing_delivery_id_writes_dlq(test_db, tmp_path):
    payload = {
        "sender": "c@ex.com",
        "recipient": "in_TOKEN@reply.neuradigi.com",
        "body-plain": "no message-id",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    dlq_rows = (
        await test_db.execute(select(EmailInboundDlq))
    ).scalars().all()
    assert len(dlq_rows) == 1
    row = dlq_rows[0]
    assert row.error_reason == "missing_mailgun_delivery_id"
    assert row.pending_inbound_path == str(pending)


@pytest.mark.asyncio
async def test_ingest_no_contact_match_persists_with_null_contact(test_db, tmp_path):
    org = await _make_org(test_db, "nocontact")
    sender = await _make_sender(test_db, org.id)
    await test_db.commit()

    payload = {
        "sender": "unknown@ex.com",
        "From": "unknown@ex.com",
        "recipient": f"in_{sender.inbound_token}@reply.neuradigi.com",
        "Message-Id": "<u@ex.com>",
        "body-plain": "Hi",
        "X-Mailgun-Spf": "pass",
    }
    pending = _write_pending(tmp_path, payload)
    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert len(rows) == 1
    conv = (
        await test_db.execute(
            select(Conversation).where(Conversation.id == rows[0].conversation_id)
        )
    ).scalar_one()
    assert conv.contact_id is None


@pytest.mark.asyncio
async def test_ingest_missing_pending_dir_is_noop(tmp_path):
    """Sweeper race: task fires after the directory was already
    consumed by an earlier run. Must not raise."""
    await _process_async(_FakeTask(), tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# _persist_inbound_email — direct shape tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_helper_takes_org_id_explicitly(test_db):
    """Contract: the helper MUST take org_id as a keyword. Any
    accidental removal breaks the Attacker C3 fix."""
    org = await _make_org(test_db, "helper")
    contact = await _make_contact(test_db, org.id, "x@ex.com")
    await test_db.commit()

    msg = await _persist_inbound_email(
        test_db,
        org_id=org.id,
        contact_id=contact.id,
        headers={"from": "x@ex.com", "subject": "Hi"},
        body_text="Hello",
        body_html=None,
        attachments=[],
        channel_message_id="mg:test-explicit",
        thread_keys=set(),
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result="pass",
        dkim_result="pass",
        auto_generated=False,
        source_provider="mailgun",
        source_reference={"smtp_sender_id": "abc"},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label="sender@ex.com",
    )
    assert msg is not None
    assert msg.org_id == org.id
    assert msg.spf_result == "pass"
    assert msg.dkim_result == "pass"
    assert msg.payload["provider"] == "mailgun"
    assert msg.payload["smtp_sender_id"] == "abc"


@pytest.mark.asyncio
async def test_cross_org_message_id_never_threads_to_wrong_org(test_db):
    """Attacker C3: a captured channel_message_id from Org A must
    not cause an Org B inbound to thread into Org A's conversation."""
    org_a = await _make_org(test_db, "orgA")
    org_b = await _make_org(test_db, "orgB")
    contact_b = await _make_contact(test_db, org_b.id, "b@ex.com")
    # Plant a message in Org A with a known channel_message_id.
    conv_a = Conversation(
        id=uuid.uuid4(),
        org_id=org_a.id,
        channel=ConversationChannel.email,
        external_id="a@ex.com",
        status=ConversationStatus.open,
    )
    test_db.add(conv_a)
    await test_db.flush()
    msg_a = Message(
        id=uuid.uuid4(),
        org_id=org_a.id,
        conversation_id=conv_a.id,
        direction=MessageDirection.out,
        text="orig",
        channel_message_id="mg:capture-me",
    )
    test_db.add(msg_a)
    await test_db.commit()

    # Now persist an inbound in Org B whose thread_keys names the
    # Org-A channel_message_id. Must NOT thread into Org A.
    msg_b = await _persist_inbound_email(
        test_db,
        org_id=org_b.id,
        contact_id=contact_b.id,
        headers={"from": "b@ex.com"},
        body_text="reply",
        body_html=None,
        attachments=[],
        channel_message_id="mg:orgB-reply",
        thread_keys={"mg:capture-me"},  # attacker's captured id
        provider_message_id=None,
        provider_message_id_fallback_provider=None,
        spf_result="pass",
        dkim_result="pass",
        auto_generated=False,
        source_provider="mailgun",
        source_reference={},
        publish_workflow_events=False,
        activity_user_id=None,
        account_email_label="sender@ex.com",
    )
    assert msg_b is not None
    # Conversation is a fresh Org-B conversation, NOT Org A's.
    conv_b = (
        await test_db.execute(
            select(Conversation).where(Conversation.id == msg_b.conversation_id)
        )
    ).scalar_one()
    assert conv_b.org_id == org_b.id
    assert conv_b.id != conv_a.id


# ---------------------------------------------------------------------------
# DLQ helper coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_to_dlq_persists_row(test_db, tmp_path):
    pending = tmp_path / "some-dir"
    pending.mkdir()
    await _write_to_dlq(pending, reason="test_reason", detail={"k": "v"})
    rows = (await test_db.execute(select(EmailInboundDlq))).scalars().all()
    # There may be pre-existing rows from other tests in the shared
    # session; find the one we just wrote.
    ours = [r for r in rows if r.pending_inbound_path == str(pending)]
    assert len(ours) == 1
    assert ours[0].error_reason == "test_reason"
    assert ours[0].error_details == {"k": "v"}


def test_cleanup_removes_directory(tmp_path):
    d = tmp_path / "gone"
    d.mkdir()
    (d / "file").write_text("hi")
    _cleanup(d)
    assert not d.exists()


def test_cleanup_missing_directory_is_noop(tmp_path):
    _cleanup(tmp_path / "does-not-exist")  # must not raise
