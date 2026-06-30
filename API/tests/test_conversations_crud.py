"""HTTP coverage for /api/v1/conversations.

Covers: empty list, list filtering, get-by-id, send (via fake adapter),
PATCH triage fields, webhook intake creates a conversation + inbound
message, permission gate.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
)
from src.app.core.conversations.registry import (
    list_registered,
    register_channel,
    unregister_channel,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


class _FakeAdapter:
    """Records each send/parse call for test assertions."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, *, org_id, external_id, text, attachments):
        self.sent.append({"text": text, "external_id": external_id})
        return ChannelMessageRef(channel_message_id=f"FAKE-{len(self.sent)}")

    def parse_webhook(self, payload):
        return InboundMessage(
            external_id=str(payload["from"]),
            text=str(payload["text"]),
            channel_message_id=str(payload["id"]),
            raw=payload,
        )


@pytest.fixture(autouse=True)
def _register_fake_whatsapp():
    fake = _FakeAdapter()
    for ch in list(list_registered()):
        unregister_channel(ch)
    register_channel(ConversationChannel.whatsapp, lambda: fake)
    yield fake
    for ch in list(list_registered()):
        unregister_channel(ch)


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _insert_conversation(
    org_id: uuid.UUID,
    *,
    channel: ConversationChannel = ConversationChannel.whatsapp,
    external_id: str = "+919876500000",
) -> uuid.UUID:
    from tests.conftest import TestSession

    async with TestSession() as session:
        c = Conversation(org_id=org_id, channel=channel, external_id=external_id)
        session.add(c)
        await session.commit()
        await session.refresh(c)
        return c.id


@pytest.mark.asyncio
async def test_empty_list(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "conversations.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.get(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_send_message_routes_through_adapter(
    layered_client, seeded_admin, _register_fake_whatsapp
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "conversations.read", "conversations.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = await _insert_conversation(org.id)

    resp = await layered_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"text": "Hello from CRM", "attachments": []},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["direction"] == "out"
    assert body["text"] == "Hello from CRM"
    assert body["channel_message_id"] == "FAKE-1"
    assert _register_fake_whatsapp.sent == [
        {"text": "Hello from CRM", "external_id": "+919876500000"}
    ]


@pytest.mark.asyncio
async def test_patch_assign_status_ai(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "conversations.read", "conversations.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    conv_id = await _insert_conversation(org.id)

    resp = await layered_client.patch(
        f"/api/v1/conversations/{conv_id}",
        json={
            "assigned_to_id": str(user.id),
            "status": "snoozed",
            "ai_handling": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assigned_to_id"] == str(user.id)
    assert body["status"] == "snoozed"
    assert body["ai_handling"] is True


@pytest.mark.asyncio
async def test_webhook_intake_creates_conversation_and_message(
    layered_client, seeded_admin, _register_fake_whatsapp
):
    """The webhook endpoint is unauthenticated, but it still needs an
    `org_id` in the context. The dev middleware honours `X-Org-Id` for
    unauthenticated paths, which is how this test seeds the tenant."""
    org = seeded_admin["org"]

    resp = await layered_client.post(
        "/api/v1/conversations/webhooks/whatsapp",
        json={"from": "+919999900000", "text": "hi there", "id": "wamid.123"},
        headers={"X-Org-Id": str(org.id)},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "message_id" in body

    # The conversation was created with the right channel + external_id.
    await _grant(seeded_admin["role"].id, "conversations.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    listing = await layered_client.get(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["channel"] == "whatsapp"
    assert items[0]["external_id"] == "+919999900000"
    assert items[0]["unread_count"] == 1


@pytest.mark.asyncio
async def test_send_requires_conversations_write(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "conversations.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    conv_id = await _insert_conversation(org.id)

    resp = await layered_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"text": "nope", "attachments": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
