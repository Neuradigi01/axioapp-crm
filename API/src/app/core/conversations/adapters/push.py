"""Push notification channel adapter — stub.

Step 13 of ``tasks/template-library`` registers a Push adapter so the
editor + the channel registry treat ``push`` as a first-class
channel — but ``send()`` raises :class:`PushNotConfigured` until a
real provider (Firebase Cloud Messaging / OneSignal / APNS) is
wired in a future push-channel track.

Inbound (`parse_webhook`) is :class:`NotImplementedError` for the
same reason — push providers don't deliver inbound messages (no
conversation surface). The method is here only because every
:class:`ChannelAdapter` is required to implement it.

Why a stub at all?

* Push templates are normal CRM artifacts — operators draft a
  title + body + action URL, route through internal review, then
  ship via campaign or one-off send. Step 13 ships the editor
  surface so the drafting workflow is unblocked.
* Push notifications never had external template approval. The
  template's :attr:`external_status` stays ``n_a`` always.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import ConversationChannel


class PushNotConfigured(RuntimeError):
    """Raised by :meth:`PushAdapter.send` until a push provider lands.
    The UI surfaces the message verbatim so the operator knows where
    to look (the integrations page that doesn't exist yet)."""

    def __init__(self) -> None:
        super().__init__(
            "Push notification transport is not yet enabled; this is "
            "template-library only. Connect a push provider (Firebase "
            "Cloud Messaging / OneSignal / APNS) in Settings → "
            "Integrations once the push channel ships."
        )


class PushAdapter:
    """Implements :class:`ChannelAdapter` for the channel registry.

    Stateless; the future provider-aware version will resolve the
    org's push credentials per-call. Today the singleton stub is
    enough — every send fails the same way."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        raise PushNotConfigured()

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        raise NotImplementedError(
            "Push notifications have no inbound surface — providers "
            "deliver one-way only. This method exists to satisfy the "
            "ChannelAdapter protocol."
        )


# --- registration -----------------------------------------------------


def _register() -> None:
    """Register the stub adapter with the channel registry at import
    time. The conversations registry's ``resolve(channel='push')``
    returns this stub; templates / future campaign dispatch raises
    through it with a clean error message."""
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.push, lambda: PushAdapter())


_register()


__all__ = ["PushAdapter", "PushNotConfigured"]
