"""Instagram Direct channel adapter — Meta Messaging Platform.

Sends via ``POST /{ig_business_id}/messages`` with the linked Page's
Page-access token; receives via Meta's Instagram webhook
(``object="instagram"``, ``entry[].messaging[]``) fanned out from
``core/integrations/meta/webhook.py``.

Meta's Messaging Platform is unified between Messenger and IG Direct,
so this adapter delegates parsing + send-response handling + token
resolution to helpers exported from ``facebook.py``. The only
IG-specific bit is:

  - The endpoint id on the conversation is the **linked Instagram
    Business Account ID**, not the Facebook Page ID.
  - The token used to authenticate the send is still the Page-access
    token of the Facebook Page linked to that IG account. Meta ties
    them together at the Page level.

Session window: same as Messenger (24-hour customer-care window).
Meta enforces on their side; adapter surfaces the error to the
composer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from config import META_GRAPH_API_VERSION
from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.adapters.facebook import (
    FacebookNotConfigured,
    _build_message_body,
    _handle_send_response,
    _parse_meta_messaging_event,
    _resolve_page_token,
)
from src.app.core.conversations.models import ConversationChannel

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com"
_HTTP_TIMEOUT = 15.0


class InstagramNotConfigured(FacebookNotConfigured):
    """Raised when the linked IG Business Account has no cached Page
    token — usually means the Meta integration was disconnected or
    the IG account was unlinked from the Facebook Page. Same error
    class hierarchy as :class:`FacebookNotConfigured` so the composer
    branch handles both."""


class InstagramAdapter:
    """Instagram Direct transport. Endpoint id is the linked IG
    Business Account ID; auth token is the linked Facebook Page's
    Page-access token, cached in ``tbl_meta_page_tokens`` under the
    IG Business Account ID (populated during ``subscribe_page_messaging``
    on connect)."""

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
        received_via_phone_id: str | None = None,
        message_tag: str | None = None,
    ) -> ChannelMessageRef:
        if not received_via_phone_id:
            raise InstagramNotConfigured(
                "Cannot send Instagram DM — no IG Business Account ID on "
                "this conversation. Reconnect the Meta integration."
            )

        page_token = await _resolve_page_token(
            org_id=org_id,
            endpoint_id=received_via_phone_id,
        )

        body: dict[str, Any] = {
            "recipient": {"id": external_id},
            "message": _build_message_body(text=text, attachments=attachments),
            "messaging_type": "MESSAGE_TAG" if message_tag else "RESPONSE",
        }
        if message_tag:
            body["tag"] = message_tag

        # IG uses the linked Facebook Page's `me/messages` endpoint
        # when the token is a Page token — Meta documented this as
        # the correct path for Instagram Messaging as of v18.0.
        url = f"{_GRAPH_BASE}/{META_GRAPH_API_VERSION}/me/messages"
        params = {"access_token": page_token}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(url, params=params, json=body)
        return _handle_send_response(response)

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Meta IG messaging event → InboundMessage.

        Identical envelope to Messenger's — same helper does both."""
        return _parse_meta_messaging_event(payload)


# --- registration -----------------------------------------------------


def _register() -> None:
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.instagram, lambda: InstagramAdapter())


_register()


__all__ = ["InstagramAdapter", "InstagramNotConfigured"]
