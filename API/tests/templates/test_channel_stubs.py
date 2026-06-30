"""Pin tests for the Step-13 FB / IG / push stub adapters.

Covers:
  * Each of the three stubs is registered with the channel registry
    so the editor + future campaign dispatch can resolve a channel
    without `ChannelNotRegistered`, AND ``send()`` raises its
    dedicated ``*NotConfigured`` exception with a human-readable
    message — the operator sees the text directly through the API
    surface.
  * Each stub's ``parse_webhook()`` raises ``NotImplementedError``
    until the real inbound surface ships.
  * The Python ``ConversationChannel`` enum carries ``push`` (the
    migration ``0124_add_push_channel_enum`` adds it on the DB side).

These three adapters mirror the SMS pattern (Step 12). The intent is
identical: ship the editor surface, fail the send cleanly.
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.conversations import registry as channel_registry
from src.app.core.conversations.adapters.facebook import (
    FacebookAdapter,
    FacebookNotConfigured,
)
from src.app.core.conversations.adapters.instagram import (
    InstagramAdapter,
    InstagramNotConfigured,
)
from src.app.core.conversations.adapters.push import (
    PushAdapter,
    PushNotConfigured,
)
from src.app.core.conversations.models import ConversationChannel

pytestmark = pytest.mark.asyncio


async def test_facebook_adapter_registered_and_send_raises_not_configured():
    """FB Messenger resolves through the registry and refuses to send."""
    resolved = channel_registry.resolve(ConversationChannel.facebook)
    assert isinstance(resolved, FacebookAdapter)
    with pytest.raises(FacebookNotConfigured) as excinfo:
        await resolved.send(
            org_id=uuid.uuid4(),
            external_id="1234567890",
            text="hi",
            attachments=[],
        )
    assert "Facebook Messenger" in str(excinfo.value)
    assert "template-library only" in str(excinfo.value)


async def test_instagram_adapter_registered_and_send_raises_not_configured():
    """IG Direct resolves through the registry and refuses to send."""
    resolved = channel_registry.resolve(ConversationChannel.instagram)
    assert isinstance(resolved, InstagramAdapter)
    with pytest.raises(InstagramNotConfigured) as excinfo:
        await resolved.send(
            org_id=uuid.uuid4(),
            external_id="ig-user-1",
            text="hi",
            attachments=[],
        )
    assert "Instagram Direct" in str(excinfo.value)
    assert "template-library only" in str(excinfo.value)


async def test_push_adapter_registered_and_send_raises_not_configured():
    """Push resolves through the registry and refuses to send."""
    resolved = channel_registry.resolve(ConversationChannel.push)
    assert isinstance(resolved, PushAdapter)
    with pytest.raises(PushNotConfigured) as excinfo:
        await resolved.send(
            org_id=uuid.uuid4(),
            external_id="device-token-abc",
            text="hi",
            attachments=[],
        )
    assert "Push notification" in str(excinfo.value)
    assert "template-library only" in str(excinfo.value)


def test_all_three_stub_parse_webhook_is_not_implemented():
    """No inbound surface ships in this step — every parse_webhook
    raises ``NotImplementedError`` so the future webhook routing
    code fails loudly until the real adapter lands."""
    for adapter in (FacebookAdapter(), InstagramAdapter(), PushAdapter()):
        with pytest.raises(NotImplementedError):
            adapter.parse_webhook({"any": "payload"})


def test_push_channel_enum_value_exists():
    """The Python-side enum carries the new ``push`` value the
    migration adds to the Postgres ``conversation_channel`` type."""
    assert ConversationChannel.push.value == "push"
    assert "push" in {member.value for member in ConversationChannel}
