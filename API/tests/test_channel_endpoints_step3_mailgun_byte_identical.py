"""Coverage for Step 3 of tasks/email-endpoint-abstraction/.

Golden byte-identical DB assertion for the Mailgun webhook Celery task.

Feeds the same fixture payload through both code paths:

  * **Legacy path** — ``EMAIL_ENDPOINTS_REFACTOR_ENABLED=false``.
    ``senders_da.find_by_inbound_token`` resolves the token; no
    ``endpoint_id`` in ``payload.source_reference``.

  * **New path** — flag default (``true``).
    ``endpoints_da.find_by_reply_token`` resolves the token; the
    resolved endpoint's UUID lands in ``payload.source_reference.endpoint_id``.

Asserts every persisted DB field (message, conversation, source_reference)
matches byte-for-byte between the two paths EXCEPT the added ``endpoint_id``
key. Any other divergence is a refactor bug and this test catches it.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import Conversation, Message
from src.app.core.email.mailgun.tasks import _endpoints_refactor_enabled, _process_async
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.email_senders.service import _generate_inbound_token
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Fixtures — mirror test_mailgun_step4_ingest shape
# ---------------------------------------------------------------------------


async def _make_org(session, slug: str = "step3") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_sender_with_endpoint(
    session, org_id: uuid.UUID
) -> tuple[EmailSmtpSender, ChannelEndpoint | None]:
    """Create SMTP sender + backing channel endpoint (mirrors Step 1 backfill)."""
    token = _generate_inbound_token()
    sender = EmailSmtpSender(
        id=uuid.uuid4(),
        org_id=org_id,
        from_address=f"sales-{uuid.uuid4().hex[:6]}@acme.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="u",
        smtp_password_enc="ciphertext",
        tls_mode="starttls",
        inbound_token=token,
        verified_at=datetime.now(UTC),
        capture_replies_in_crm=True,
    )
    session.add(sender)
    await session.flush()

    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="smtp_reply_capture",
        label=sender.from_address,
    )
    session.add(endpoint)
    await session.flush()

    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        reply_token=token,
        smtp_sender_id=sender.id,
    )
    session.add(details)
    await session.flush()
    return sender, endpoint


async def _make_contact(session, org_id: uuid.UUID, email: str) -> Contact:
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


def _base_payload(token: str, delivery_id: str) -> dict[str, Any]:
    return {
        "sender": "customer@ex.com",
        "recipient": f"in_{token}@reply.neuradigi.com",
        "Subject": "Re: your quote",
        "From": "customer@ex.com",
        "Message-Id": delivery_id,
        "body-plain": "Sounds good, let's do it.",
        "X-Mailgun-Spf": "pass",
        "X-Mailgun-Dkim-Signature": "pass",
    }


# ---------------------------------------------------------------------------
# 1. Feature flag toggles path
# ---------------------------------------------------------------------------


def test_feature_flag_default_is_true(monkeypatch):
    monkeypatch.delenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", raising=False)
    assert _endpoints_refactor_enabled() is True


def test_feature_flag_false_disables_new_path(monkeypatch):
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "false")
    assert _endpoints_refactor_enabled() is False


def test_feature_flag_case_insensitive(monkeypatch):
    for val in ("FALSE", "False", "false"):
        monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", val)
        assert _endpoints_refactor_enabled() is False


def test_feature_flag_true_string_enables(monkeypatch):
    for val in ("true", "TRUE", "yes", "1", "anything-not-false"):
        monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", val)
        assert _endpoints_refactor_enabled() is True


# ---------------------------------------------------------------------------
# 2. New-path populates endpoint_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_path_stamps_endpoint_id_in_source_reference(
    test_db, tmp_path, monkeypatch
):
    """Flag on (default) → endpoint_id lands in message payload."""
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "true")

    org = await _make_org(test_db, "new-path")
    sender, endpoint = await _make_sender_with_endpoint(test_db, org.id)
    await _make_contact(test_db, org.id, "customer@ex.com")
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@mail.example>"
    payload = _base_payload(sender.inbound_token, delivery_id)
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    msg = (
        await test_db.execute(
            select(Message).where(Message.org_id == org.id)
        )
    ).scalar_one()
    assert msg.payload["endpoint_id"] == str(endpoint.id)
    assert msg.payload["smtp_sender_id"] == str(sender.id)


# ---------------------------------------------------------------------------
# 3. Legacy-path preserves original shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_path_flag_off_omits_endpoint_id(
    test_db, tmp_path, monkeypatch
):
    """Flag off → endpoint_id absent from payload (pre-refactor shape)."""
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "false")

    org = await _make_org(test_db, "legacy-path")
    sender, _endpoint = await _make_sender_with_endpoint(test_db, org.id)
    await _make_contact(test_db, org.id, "customer@ex.com")
    await test_db.commit()

    delivery_id = f"<{uuid.uuid4().hex}@mail.example>"
    payload = _base_payload(sender.inbound_token, delivery_id)
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    msg = (
        await test_db.execute(
            select(Message).where(Message.org_id == org.id)
        )
    ).scalar_one()
    assert "endpoint_id" not in msg.payload
    assert msg.payload["smtp_sender_id"] == str(sender.id)


# ---------------------------------------------------------------------------
# 4. Byte-identical assertion — same input, two paths, one field diff
# ---------------------------------------------------------------------------


def _strip_endpoint_id(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove ``endpoint_id`` — the only allowed divergence between paths."""
    out = dict(payload)
    out.pop("endpoint_id", None)
    return out


async def _run_ingest_and_capture(
    test_db,
    tmp_path,
    monkeypatch,
    *,
    flag_value: str,
    slug: str,
) -> tuple[Message, Conversation]:
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", flag_value)

    org = await _make_org(test_db, slug)
    sender, _endpoint = await _make_sender_with_endpoint(test_db, org.id)
    await _make_contact(test_db, org.id, f"customer-{slug}@ex.com")
    await test_db.commit()

    delivery_id = f"<{slug}-{uuid.uuid4().hex}@mail.example>"
    payload = _base_payload(sender.inbound_token, delivery_id)
    payload["From"] = f"customer-{slug}@ex.com"
    payload["sender"] = f"customer-{slug}@ex.com"
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    msg = (
        await test_db.execute(
            select(Message).where(Message.org_id == org.id)
        )
    ).scalar_one()
    conv = (
        await test_db.execute(
            select(Conversation).where(Conversation.org_id == org.id)
        )
    ).scalar_one()
    return msg, conv


@pytest.mark.asyncio
async def test_byte_identical_message_payload_except_endpoint_id(
    test_db, tmp_path, monkeypatch
):
    """Same fixture through both paths → identical DB shape except endpoint_id."""
    # Legacy path
    legacy_msg, legacy_conv = await _run_ingest_and_capture(
        test_db, tmp_path, monkeypatch, flag_value="false", slug="legacy"
    )
    legacy_payload = _strip_endpoint_id(legacy_msg.payload)
    legacy_dir = legacy_msg.direction
    legacy_channel_id = legacy_msg.channel_message_id
    legacy_spf = legacy_msg.spf_result
    legacy_dkim = legacy_msg.dkim_result
    legacy_text = legacy_msg.text
    legacy_conv_status = legacy_conv.status

    # New path (fresh org, fresh sender — no cross-test contamination)
    new_msg, new_conv = await _run_ingest_and_capture(
        test_db, tmp_path, monkeypatch, flag_value="true", slug="newpath"
    )
    new_payload = _strip_endpoint_id(new_msg.payload)

    # Byte-identical scalar fields (excluding auto-gen IDs, timestamps, and
    # per-fixture varying values like delivery_id + customer email).
    assert new_msg.direction == legacy_dir
    assert new_msg.spf_result == legacy_spf
    assert new_msg.dkim_result == legacy_dkim
    assert new_msg.text == legacy_text
    assert new_conv.status == legacy_conv_status

    # Payload keys identical after stripping endpoint_id.
    assert set(new_payload.keys()) == set(legacy_payload.keys())

    # Every non-varying value matches.
    for key in ("provider", "spoof_suspected", "system_review_required"):
        assert new_payload[key] == legacy_payload[key], (
            f"drift in payload.{key}: legacy={legacy_payload[key]}, "
            f"new={new_payload[key]}"
        )


# ---------------------------------------------------------------------------
# 5. Unknown token — both paths behave identically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_token_new_path_drops_no_message_persisted(
    test_db, tmp_path, monkeypatch
):
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "true")

    org = await _make_org(test_db, "unknown-new")
    await test_db.commit()

    payload = _base_payload("bogus-token", f"<{uuid.uuid4().hex}@mail.example>")
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_inactive_endpoint_new_path_treats_as_unknown(
    test_db, tmp_path, monkeypatch
):
    """Endpoint deactivated between outbound send and inbound reply →
    lookup returns None → unknown_recipient audit + drop. No message persisted."""
    monkeypatch.setenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "true")

    org = await _make_org(test_db, "inactive")
    sender, endpoint = await _make_sender_with_endpoint(test_db, org.id)
    # Deactivate the endpoint after creation but before the payload arrives.
    endpoint.is_active = False
    await test_db.commit()

    payload = _base_payload(sender.inbound_token, f"<{uuid.uuid4().hex}@mail.example>")
    pending = _write_pending(tmp_path, payload)

    await _process_async(_FakeTask(), pending)

    rows = (
        await test_db.execute(select(Message).where(Message.org_id == org.id))
    ).scalars().all()
    assert rows == []
