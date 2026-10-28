"""Instagram Direct channel adapter — stub.

Step 13 of ``tasks/template-library`` registers an Instagram Direct
adapter so the editor + the channel registry treat ``instagram`` as
a first-class channel — but ``send()`` raises
:class:`InstagramNotConfigured` until the Instagram Messaging API
integration lands (Instagram Professional account + connected
Facebook Page + webhook subscription).

Inbound (`parse_webhook`) is :class:`NotImplementedError` for the
same reason — no Messaging-API subscription, no inbound.

Why a stub at all?

* Templates for IG Direct are normal CRM artifacts; operators draft
  them, route through internal review, then ship via campaign or
  one-off send. Step 13 ships the editor surface so the drafting
  workflow is unblocked.
* Instagram never had message templates — the external-approval
  workflow doesn't exist for IG. :attr:`external_status` stays
  ``n_a`` for every IG template.
* Meta's Instagram Messaging API and Messenger Platform are the
  same surface (one Page-Access Token, one webhook envelope), which
  is why the editor reuses the FB sub-form for both channels.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import ConversationChannel


class InstagramNotConfigured(RuntimeError):
    """Raised by :meth:`InstagramAdapter.send` until the IG Messaging
    integration is wired. The UI surfaces the message verbatim."""

    def __init__(self) -> None:
        super().__init__(
            "Instagram Direct transport is not yet enabled; this is "
            "template-library only. Connect an Instagram Professional "
            "account in Settings → Integrations once the Messaging "
            "channel ships."
        )


class InstagramAdapter:
    """Implements :class:`ChannelAdapter` for the channel registry.

    Stateless; the future provider-aware version will resolve the
    connected Instagram account per-org. Today the singleton stub is
    enough — every send fails the same way."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        raise InstagramNotConfigured()

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        raise NotImplementedError(
            "Instagram Direct inbound webhook handler ships with the "
            "Messaging Platform adapter — not in scope for the "
            "template-library track."
        )


# --- registration -----------------------------------------------------


def _register() -> None:
    """Register the stub adapter with the channel registry at import
    time. The conversations registry's ``resolve(channel='instagram')``
    returns this stub; templates / future campaign dispatch raises
    through it with a clean error message."""
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.instagram, lambda: InstagramAdapter())


_register()


__all__ = ["InstagramAdapter", "InstagramNotConfigured"]
