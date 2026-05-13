"""Channel adapter registry — register / resolve / unregister + outbound dispatch.

A fake adapter records every `send()` invocation so the test can
assert the engine routed through it. The registry must dispatch by
`conversation.channel`; resolving an unregistered channel raises.
"""
from __future__ import annotations

import uuid

import pytest

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
    MessageDirection,
)
from src.app.core.conversations.registry import (
    ChannelNotRegistered,
    list_registered,
    register_channel,
    resolve,
    unregister_channel,
)
from src.app.core.conversations.service import send_outbound


class FakeWhatsAppAdapter:
    """Records every send() call. parse_webhook is a no-op identity."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, object]],
    ) -> ChannelMessageRef:
        self.sent.append(
            {
                "org_id": org_id,
                "external_id": external_id,
                "text": text,
                "attachments": attachments,
            }
        )
        return ChannelMessageRef(channel_message_id=f"fake-{len(self.sent)}")

    def parse_webhook(self, payload):
        return InboundMessage(
            external_id=str(payload.get("from", "")),
            text=str(payload.get("text", "")),
            channel_message_id=str(payload.get("id", "")),
            raw=payload,
        )


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with a fresh registry."""
    for ch in list(list_registered()):
        unregister_channel(ch)
    yield
    for ch in list(list_registered()):
        unregister_channel(ch)


def test_resolve_raises_for_unregistered_channel():
    with pytest.raises(ChannelNotRegistered):
        resolve(ConversationChannel.whatsapp)


def test_register_and_resolve_returns_factory_instance():
    fake = FakeWhatsAppAdapter()
    register_channel(ConversationChannel.whatsapp, lambda: fake)

    adapter = resolve(ConversationChannel.whatsapp)
    assert adapter is fake
    assert ConversationChannel.whatsapp in list_registered()


def test_unregister_drops_factory():
    register_channel(ConversationChannel.whatsapp, lambda: FakeWhatsAppAdapter())
    unregister_channel(ConversationChannel.whatsapp)
    with pytest.raises(ChannelNotRegistered):
        resolve(ConversationChannel.whatsapp)


@pytest.mark.asyncio
async def test_send_outbound_routes_through_registered_adapter(
    test_db, seeded_admin
):
    """`send_outbound` resolves the adapter for `conversation.channel`,
    calls its `send()`, persists the outbound row, and bumps the
    conversation's `last_message_at`."""
    fake = FakeWhatsAppAdapter()
    register_channel(ConversationChannel.whatsapp, lambda: fake)

    conv = Conversation(
        org_id=seeded_admin["org"].id,
        channel=ConversationChannel.whatsapp,
        external_id="+919876500000",
    )
    test_db.add(conv)
    await test_db.commit()
    await test_db.refresh(conv)

    msg = await send_outbound(
        test_db,
        conversation_id=conv.id,
        user_id=seeded_admin["user"].id,
        text_body="Hello from CRM",
        attachments=[],
    )

    assert msg.direction == MessageDirection.out
    assert msg.text == "Hello from CRM"
    assert msg.channel_message_id == "fake-1"
    assert len(fake.sent) == 1
    assert fake.sent[0]["external_id"] == "+919876500000"
    assert fake.sent[0]["text"] == "Hello from CRM"

    await test_db.refresh(conv)
    assert conv.last_message_at is not None


@pytest.mark.asyncio
async def test_send_outbound_unregistered_channel_raises(
    test_db, seeded_admin
):
    """Without a registered adapter for the conversation's channel,
    `send_outbound` propagates `ChannelNotRegistered`."""
    conv = Conversation(
        org_id=seeded_admin["org"].id,
        channel=ConversationChannel.sms,
        external_id="+919876500000",
    )
    test_db.add(conv)
    await test_db.commit()
    await test_db.refresh(conv)

    with pytest.raises(ChannelNotRegistered):
        await send_outbound(
            test_db,
            conversation_id=conv.id,
            user_id=seeded_admin["user"].id,
            text_body="hi",
            attachments=[],
        )
