"""WhatsApp webhook intake — full HTTP round-trip through the router.

The router-level test exercises:
  - GET handshake (`hub.mode=subscribe`) returns the challenge.
  - POST signature verification (bad → 403, good → 202).
  - parse_webhook → engine → DB: a conversation + an inbound message
    are persisted, and the contact is auto-resolved (created with
    `full_name = phone` when none matches).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

# Side-effect: ensure Contact is on Base.metadata for `create_all`.
from src.app.core.contacts import models as _contacts  # noqa: F401
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters.whatsapp import WhatsAppAdapter
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
)
from src.app.core.conversations.registry import (
    list_registered,
    register_channel,
    unregister_channel,
)


APP_SECRET = "wa-test-secret"
VERIFY_TOKEN = "wa-verify-tok"


@pytest.fixture(autouse=True)
def _register_test_whatsapp():
    """Swap in a deterministic WhatsAppAdapter instance with the
    secrets the tests sign their payloads with."""
    adapter = WhatsAppAdapter(
        phone_id="P",
        token="T",
        app_secret=APP_SECRET,
        verify_token=VERIFY_TOKEN,
    )
    for ch in list(list_registered()):
        unregister_channel(ch)
    register_channel(ConversationChannel.whatsapp, lambda: adapter)
    yield adapter
    for ch in list(list_registered()):
        unregister_channel(ch)


def _sign(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _sample_envelope(
    sender_phone: str = "919876500000",
    text: str = "Hi from a customer",
    wamid: str = "wamid.HBgL12345",
) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender_phone,
                                    "id": wamid,
                                    "timestamp": "1700000000",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@pytest.mark.asyncio
async def test_verify_handshake_returns_challenge(layered_client):
    resp = await layered_client.get(
        "/api/v1/conversations/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "42",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.text == "42"


@pytest.mark.asyncio
async def test_verify_handshake_wrong_token_returns_403(layered_client):
    resp = await layered_client.get(
        "/api/v1/conversations/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "42",
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(
    layered_client, seeded_admin
):
    body = json.dumps(_sample_envelope()).encode()
    resp = await layered_client.post(
        "/api/v1/conversations/webhooks/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": "sha256=deadbeef",
            "X-Org-Id": str(seeded_admin["org"].id),
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_webhook_persists_message_and_creates_contact(
    layered_client, seeded_admin
):
    body = json.dumps(_sample_envelope()).encode()
    resp = await layered_client.post(
        "/api/v1/conversations/webhooks/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": _sign(body),
            "X-Org-Id": str(seeded_admin["org"].id),
        },
    )
    assert resp.status_code == 202, resp.text

    from tests.conftest import TestSession

    async with TestSession() as session:
        convs = (await session.execute(select(Conversation))).scalars().all()
        assert len(convs) == 1
        conv = convs[0]
        assert conv.channel == ConversationChannel.whatsapp
        assert conv.external_id == "+919876500000"
        assert conv.unread_count == 1
        assert conv.contact_id is not None

        msgs = (await session.execute(select(Message))).scalars().all()
        assert len(msgs) == 1
        assert msgs[0].text == "Hi from a customer"
        assert msgs[0].channel_message_id == "wamid.HBgL12345"

        # Auto-created contact named after phone.
        contact = (
            await session.execute(
                select(Contact).where(Contact.id == conv.contact_id)
            )
        ).scalar_one()
        assert contact.phone == "+919876500000"
        assert contact.full_name == "+919876500000"
        assert contact.source == "whatsapp"


@pytest.mark.asyncio
async def test_webhook_existing_contact_reused(
    layered_client, seeded_admin
):
    """If a contact with the matching phone already exists, link to
    it instead of creating a duplicate placeholder."""
    from tests.conftest import TestSession

    async with TestSession() as session:
        c = Contact(
            org_id=seeded_admin["org"].id,
            full_name="Rakesh Kumar",
            phone="+919876500000",
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        existing_id = c.id

    body = json.dumps(_sample_envelope()).encode()
    resp = await layered_client.post(
        "/api/v1/conversations/webhooks/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": _sign(body),
            "X-Org-Id": str(seeded_admin["org"].id),
        },
    )
    assert resp.status_code == 202, resp.text

    async with TestSession() as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.contact_id == existing_id
        # No duplicate contact got minted.
        contacts = (await session.execute(select(Contact))).scalars().all()
        assert len(contacts) == 1


@pytest.mark.asyncio
async def test_webhook_unparseable_envelope_returns_400(
    layered_client, seeded_admin
):
    body = json.dumps({"hello": "world"}).encode()
    resp = await layered_client.post(
        "/api/v1/conversations/webhooks/whatsapp",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": _sign(body),
            "X-Org-Id": str(seeded_admin["org"].id),
        },
    )
    assert resp.status_code == 400, resp.text
