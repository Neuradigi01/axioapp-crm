"""Facebook Messenger channel adapter — Meta Messaging Platform.

Sends via ``POST /{page_id}/messages`` with the cached Page-access
token; receives via Meta's page webhook (``object="page"``,
``entry[].messaging[]``) fanned out from
``core/integrations/meta/webhook.py``.

Session-window: Meta enforces a 24-hour customer-care window on
Messenger. Sends outside the window need a `MESSAGE_TAG` category
(``ACCOUNT_UPDATE`` / ``CONFIRMED_EVENT_UPDATE`` / etc.). The adapter
does NOT enforce this client-side — Meta rejects out-of-window sends
at the API with a clear error code we surface to the composer.

The Instagram Direct adapter shares almost all of this logic — Meta's
Messaging Platform is unified. The differences are:
  - IG uses ``object="instagram"`` on the webhook envelope
  - IG uses the linked Instagram Business Account ID as the endpoint,
    not the Page ID
The webhook receiver already translates both into the same
``InboundMessage`` shape via each adapter's ``parse_webhook``.
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
from src.app.core.conversations.models import ConversationChannel

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com"
_HTTP_TIMEOUT = 15.0


class FacebookNotConfigured(RuntimeError):
    """Raised when we can't resolve a Page-access token for the
    conversation's endpoint. Usually means the Meta integration was
    disconnected or the Page was unsubscribed after the conversation
    was opened. The composer surfaces the message verbatim."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class FacebookAdapter:
    """Real Messenger transport backed by the Meta Graph API.

    Stateless. Per-request the adapter resolves a Page-access token
    from ``tbl_meta_page_tokens`` (populated during
    :func:`subscribe_page_messaging` on connect). The lookup key is
    the conversation's ``received_via_phone_id`` (overloaded to store
    the Page ID for FB / IG Business Account ID for IG)."""

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
        """POST /{page_id}/messages to Meta. `external_id` is the
        recipient's Page-Scoped ID (PSID). `received_via_phone_id`
        overloaded to carry the Page ID.

        `message_tag` — optional Meta message tag (e.g.
        ``ACCOUNT_UPDATE``) for out-of-window sends. When omitted,
        Meta enforces the 24-hour window on its side."""
        if not received_via_phone_id:
            raise FacebookNotConfigured(
                "Cannot send Messenger reply — no Page ID on this "
                "conversation. Reconnect the Meta integration."
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

        url = f"{_GRAPH_BASE}/{META_GRAPH_API_VERSION}/{received_via_phone_id}/messages"
        params = {"access_token": page_token}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(url, params=params, json=body)
        return _handle_send_response(response)

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Meta Messaging event → InboundMessage.

        Payload here is a single ``entry.messaging[i]`` item (the
        webhook receiver already unwrapped the outer envelope + fanned
        out). Shape::

            {
              "sender": {"id": "PSID"},
              "recipient": {"id": "PAGE_ID"},
              "timestamp": 1234567890,
              "message": {"mid": "...", "text": "hello"} | postback | ...
            }
        """
        return _parse_meta_messaging_event(payload)


# --- helpers ---------------------------------------------------------------


def _build_message_body(
    *,
    text: str,
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Meta's outbound message shape. Text goes in ``message.text``;
    a single attachment (Meta caps at 1 per send) goes in
    ``message.attachment``. Text-only is the common case; a media send
    can omit ``text``."""
    body: dict[str, Any] = {}
    if text:
        body["text"] = text
    if attachments:
        first = attachments[0]
        att_type = str(first.get("type") or "image").lower()
        url = first.get("url")
        if url:
            body["attachment"] = {
                "type": att_type,
                "payload": {"url": url, "is_reusable": False},
            }
    if not body:
        raise FacebookNotConfigured(
            "Messenger send requires either text or an attachment."
        )
    return body


def _handle_send_response(response: httpx.Response) -> ChannelMessageRef:
    """Map Meta's response → ChannelMessageRef or raise."""
    try:
        body = response.json()
    except ValueError:
        raise FacebookNotConfigured(
            f"Meta returned non-JSON on send (status={response.status_code}): "
            f"{response.text[:200]}"
        ) from None

    if response.status_code >= 400 or "error" in body:
        err = body.get("error", {}) if isinstance(body, dict) else {}
        raise FacebookNotConfigured(
            f"Meta rejected Messenger send: {err.get('message') or body}"
        )

    mid = body.get("message_id")
    if not mid:
        raise FacebookNotConfigured(
            f"Meta response missing message_id: {body}"
        )
    return ChannelMessageRef(
        channel_message_id=str(mid),
        sent_at=datetime.now(UTC),
    )


def _parse_meta_messaging_event(event: dict[str, Any]) -> InboundMessage:
    """Turn a single Messenger / IG Direct event into InboundMessage.

    Handles two event kinds:
      - ``message`` — normal DM (text and/or attachment)
      - ``postback`` — quick-reply button tap (payload becomes text)
    """
    sender = event.get("sender") or {}
    sender_id = sender.get("id")
    if not sender_id:
        raise ValueError("Meta messaging event missing sender.id")

    timestamp_ms = event.get("timestamp")
    sent_at: datetime | None = None
    if isinstance(timestamp_ms, (int, float)):
        sent_at = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC)

    message = event.get("message") or {}
    postback = event.get("postback") or {}

    text: str | None = None
    attachments: list[dict[str, Any]] = []
    channel_message_id: str | None = None
    reply_to_channel_message_id: str | None = None
    reaction: dict[str, Any] | None = None

    if message:
        text = message.get("text") or None
        channel_message_id = message.get("mid")
        raw_attachments = message.get("attachments") or []
        for att in raw_attachments if isinstance(raw_attachments, list) else []:
            if not isinstance(att, dict):
                continue
            payload = att.get("payload") or {}
            attachments.append(
                {
                    "type": att.get("type") or "file",
                    "url": payload.get("url") if isinstance(payload, dict) else None,
                }
            )
        reply_to = message.get("reply_to") or {}
        if isinstance(reply_to, dict):
            reply_to_channel_message_id = reply_to.get("mid")
    elif postback:
        text = postback.get("title") or postback.get("payload")
        channel_message_id = postback.get("mid")
    else:
        # `reaction` field on Messenger — rare but supported.
        reaction_event = event.get("reaction") or {}
        if isinstance(reaction_event, dict) and reaction_event.get("mid"):
            reaction = {
                "target_channel_message_id": reaction_event["mid"],
                "emoji": reaction_event.get("emoji") or "",
                "reactor_external_id": str(sender_id),
            }
        else:
            raise ValueError(
                "Meta messaging event carries neither message nor postback nor reaction"
            )

    return InboundMessage(
        external_id=str(sender_id),
        text=text,
        attachments=attachments,
        channel_message_id=channel_message_id,
        sent_at=sent_at,
        raw=dict(event),
        reply_to_channel_message_id=reply_to_channel_message_id,
        reaction=reaction,
    )


async def _resolve_page_token(
    *,
    org_id: uuid.UUID,
    endpoint_id: str,
) -> str:
    """Look up the decrypted Page-access token for this Page ID (or IG
    Business Account ID). Runs a raw-SQL lookup because the send-path
    already sits inside a request session with tenant context set."""
    from sqlalchemy import text as sql_text

    from src.app.core.integrations.crypto import decrypt
    from src.app.shared.db import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                sql_text(
                    """
                    SELECT page_token_enc
                    FROM tbl_meta_page_tokens
                    WHERE org_id = :org_id
                      AND page_id = :endpoint_id
                    LIMIT 1
                    """
                ),
                {"org_id": str(org_id), "endpoint_id": endpoint_id},
            )
        ).mappings().first()

    if row is None:
        raise FacebookNotConfigured(
            "No Page-access token cached for this conversation's endpoint. "
            "Reconnect the Meta integration in Settings → Integrations."
        )
    return decrypt(row["page_token_enc"])


# --- registration -----------------------------------------------------


def _register() -> None:
    from src.app.core.conversations.registry import register_channel

    register_channel(ConversationChannel.facebook, lambda: FacebookAdapter())


_register()


__all__ = ["FacebookAdapter", "FacebookNotConfigured"]
