"""Facebook Messenger channel adapter — stub.

Step 13 of ``tasks/template-library`` registers a Facebook Messenger
adapter so the editor + the channel registry treat ``facebook`` as
a first-class channel — but ``send()`` raises
:class:`FacebookNotConfigured` until the Meta Messaging API
integration lands (page-access-token OAuth, webhook subscription,
24-hour customer-care window enforcement).

Inbound (`parse_webhook`) is :class:`NotImplementedError` for the
same reason — no Messenger Platform subscription, no inbound.

Why a stub at all?

* Templates for FB Messenger are normal CRM artifacts — operators
  draft them, route through internal review, then ship via a future
  campaign or one-off send. Step 13 ships the editor surface so the
  drafting workflow is unblocked.
* Meta dropped FB Messenger *message templates* (the external-
  approval pipeline) post-2020. Outbound text inside the 24-hour
  human-agent window doesn't need pre-approval; outside the window
  one of Meta's "message tags" applies. Neither path requires the
  external-status workflow, so :attr:`external_status` stays
  ``n_a`` for every FB template.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import ConversationChannel


class FacebookNotConfigured(RuntimeError):
    """Raised by :meth:`FacebookAdapter.send` until the Meta Messaging
    integration is wired. The UI surfaces the message verbatim so
    the operator knows where to look (the integrations page that
    doesn't exist yet)."""

    def __init__(self) -> None:
        super().__init__(
            "Facebook Messenger transport is not yet enabled; this is "
            "template-library only. Connect a Facebook Page in "
            "Settings → Integrations once the Messenger channel ships."
        )


class FacebookAdapter:
    """Implements :class:`ChannelAdapter` for the channel registry.

    Stateless; the future provider-aware version will resolve a
    Page-Access Token per-org from a connections table (mirroring the
    WA adapter's ``resolve_whatsapp_adapter`` pattern). Today the
    singleton stub is enough — every send fails the same way."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        raise FacebookNotConfigured()

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        raise NotImplementedError(
            "Facebook Messenger inbound webhook handler ships with "
            "the Messenger Platform adapter — not in scope for the "
            "template-library track."
        )


# --- registration -----------------------------------------------------


def _register() -> None:
    """Register the stub adapter with the channel registry at import
    time. The conversations registry's ``resolve(channel='facebook')``
    returns this stub; templates / future campaign dispatch raises
    through it with a clean error message."""
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.facebook, lambda: FacebookAdapter())


_register()


__all__ = ["FacebookAdapter", "FacebookNotConfigured"]
