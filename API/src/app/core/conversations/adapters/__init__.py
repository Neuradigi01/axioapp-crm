"""Channel adapter contract for the conversations engine.

Each channel (whatsapp, instagram, web, sms, …) ships a class that
implements `ChannelAdapter` — two methods:

- `send(conversation, text, attachments) -> ChannelMessageRef` — push
  a CRM-authored outbound message through the channel's transport.
  The returned `ChannelMessageRef` carries the channel's own message
  id (so the inbox can later dedupe a webhook receipt) and an optional
  timestamp.
- `parse_webhook(payload) -> InboundMessage` — turn the raw channel
  webhook envelope into the platform-independent shape the engine
  knows how to persist. Adapters are responsible for signature
  verification *inside* this method; raising `ValueError` rejects the
  payload with 400.

The protocol intentionally has no I/O of its own — the registry
resolves an adapter instance for a `(channel)` pair and the service
calls into it. This keeps the engine channel-agnostic and lets
Step 3.9 plug in WhatsApp without changing the engine.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChannelMessageRef:
    """Result of `ChannelAdapter.send`. The id is what the channel gave
    us back; we store it on the `messages.channel_message_id` column so
    dedupe works on the inbound webhook side."""

    channel_message_id: str
    sent_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Parsed webhook payload — channel-agnostic shape.

    `external_id` is the channel-side participant identity (e.g. the
    WhatsApp phone number); the engine uses it to look up or create
    the matching `Conversation`. The raw envelope is preserved on
    `messages.payload` for debugging.

    `reply_to_channel_message_id` (Step 7) is the channel-side id of
    the message this one quotes — the engine resolves it back to our
    UUID via the unique `channel_message_id` index.

    `reaction` (Step 7) is a reaction *event* — when set, the engine
    does NOT create a new message row; it locates the target message
    (by `reaction["target_channel_message_id"]`) and applies the
    reactor's emoji to that row's `reactions` JSONB.
    """

    external_id: str
    text: str | None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    channel_message_id: str | None = None
    sent_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    reply_to_channel_message_id: str | None = None
    reaction: dict[str, Any] | None = None


class ChannelAdapter(Protocol):
    """Structural type — anything matching the two methods registers."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        ...


__all__ = [
    "ChannelAdapter",
    "ChannelMessageRef",
    "InboundMessage",
]
