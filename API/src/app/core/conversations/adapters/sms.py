"""SMS channel adapter — stub.

Step 12 of ``tasks/template-library`` registers an SMS adapter so
the editor + the channel registry treat SMS as a first-class
channel — but ``send()`` raises :class:`SMSNotConfigured` until a
real provider (Gupshup / MSG91 / Kaleyra) is wired in a future
SMS-channel track. Campaigns with SMS templates fail gracefully at
dispatch with a clear "configure an SMS provider" message instead
of mysterious 500s.

Inbound (`parse_webhook`) is :class:`NotImplementedError` for the
same reason — no provider, no inbound.
"""
from __future__ import annotations

import uuid
from typing import Any

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import ConversationChannel


class SMSNotConfigured(RuntimeError):
    """Raised by :meth:`SMSAdapter.send` until an SMS provider lands.

    The campaigns dispatcher (Step 11 already catches this kind of
    failure via ``ChannelNotRegistered`` / generic exception) marks
    the row failed + surfaces the message verbatim. UI copy comes
    straight from this exception."""

    def __init__(self) -> None:
        super().__init__(
            "SMS provider is not configured for this org. Connect "
            "Gupshup / MSG91 / Kaleyra in Settings → Integrations "
            "before launching an SMS campaign."
        )


class SMSAdapter:
    """Implements :class:`ChannelAdapter` for the channel registry.

    Stateless; the future provider-aware version will be resolved
    per-org via a config table (mirroring the WA adapter's
    ``resolve_whatsapp_adapter`` pattern). Today the singleton stub
    is enough — every send call fails the same way."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        raise SMSNotConfigured()

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        raise NotImplementedError(
            "SMS inbound webhook handler ships with the SMS-provider "
            "adapter — not in scope for the template-library track."
        )


# --- registration -----------------------------------------------------


def _register() -> None:
    """Register the stub adapter with the channel registry at import
    time. The conversations registry's ``resolve(channel='sms')``
    returns this stub; campaign dispatch raises through it with a
    clean error message."""
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.sms, lambda: SMSAdapter())


_register()


__all__ = ["SMSAdapter", "SMSNotConfigured"]
