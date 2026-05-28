"""WhatsApp Business Cloud API channel adapter.

This is the *only* place that knows about Meta's WhatsApp Cloud API
shape. The engine in `core.conversations.service` is channel-agnostic
and calls `ChannelAdapter.send` / `parse_webhook` via the registry.

What this module owns:

- `WhatsAppAdapter.send(...)`: POSTs the Cloud API "messages" endpoint
  with the JSON envelope WhatsApp expects (text body for now —
  templates / media are deferred per the step spec).
- `WhatsAppAdapter.parse_webhook(...)`: extracts the inbound message
  out of Meta's deeply-nested webhook envelope (`entry → changes →
  value → messages[]`) and returns a channel-agnostic `InboundMessage`.
- `WhatsAppAdapter.verify_signature(...)`: validates Meta's
  `X-Hub-Signature-256` header — HMAC-SHA256 of the raw request body
  with `WHATSAPP_APP_SECRET`. The webhook router rejects payloads that
  fail this check.
- `WhatsAppAdapter.verify_subscription(...)`: implements the
  Meta-required GET-time verification handshake (`hub.mode=subscribe`).

Outbound errors (non-2xx from the Cloud API) raise `WhatsAppSendError`,
which the engine surfaces as a 502 to the caller.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    WHATSAPP_API_VERSION,
    WHATSAPP_APP_SECRET,
    WHATSAPP_PHONE_ID,
    WHATSAPP_TOKEN,
    WHATSAPP_VERIFY_TOKEN,
)
from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)

logger = logging.getLogger(__name__)


class WhatsAppSendError(Exception):
    """Raised when the Cloud API returns a non-2xx."""


class WhatsAppNotConnected(Exception):
    """Raised by `resolve_whatsapp_adapter` when the active tenant has
    no `connected` `Integration` row for the `whatsapp` provider.

    Callers (conversations send + campaigns dispatch) surface this as
    HTTP 409 ("Connect WhatsApp in Settings → Integrations") or, in
    the campaigns dispatch path, mark every `CampaignMessage` row as
    `failed` with the message so the UI shows the configuration gap."""


_PHONE_RE = re.compile(r"\D+")


def _normalize_phone(raw: str) -> str:
    """E.164-ish: strip non-digits, prefix `+`. Empty input → empty out."""
    if raw is None:
        return ""
    digits = _PHONE_RE.sub("", raw)
    if not digits:
        return ""
    return f"+{digits}"


class WhatsAppAdapter:
    """Implements `ChannelAdapter` for Meta's WhatsApp Cloud API."""

    def __init__(
        self,
        *,
        phone_id: str = WHATSAPP_PHONE_ID,
        token: str = WHATSAPP_TOKEN,
        app_secret: str = WHATSAPP_APP_SECRET,
        verify_token: str = WHATSAPP_VERIFY_TOKEN,
        api_version: str = WHATSAPP_API_VERSION,
        http_client_factory: Any = None,
    ) -> None:
        self._phone_id = phone_id
        self._token = token
        self._app_secret = app_secret
        self._verify_token = verify_token
        self._api_version = api_version
        # Tests inject an httpx.AsyncClient or a stand-in. Default is a
        # fresh client per call so we never leak connections across
        # process restarts.
        self._http_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=10.0)
        )

    @property
    def endpoint(self) -> str:
        return (
            f"https://graph.facebook.com/{self._api_version}/"
            f"{self._phone_id}/messages"
        )

    # --- outbound ----------------------------------------------------------

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        """POST a text message to Meta's Cloud API.

        `attachments` is accepted for protocol parity but ignored here —
        media uploads + templates are deferred per the step spec.
        """
        to = _normalize_phone(external_id).lstrip("+")
        envelope = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._http_factory() as client:
            resp = await client.post(
                self.endpoint, json=envelope, headers=headers
            )
        if resp.status_code >= 400:
            raise WhatsAppSendError(
                f"whatsapp send failed: {resp.status_code} {resp.text}"
            )
        body = resp.json()
        msg_id = (
            body.get("messages", [{}])[0].get("id")
            if isinstance(body, dict)
            else None
        )
        return ChannelMessageRef(
            channel_message_id=str(msg_id) if msg_id else "",
            sent_at=datetime.now(timezone.utc),
        )

    # --- inbound -----------------------------------------------------------

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Pull the first message out of a Cloud API webhook envelope.

        Envelope shape (simplified):

            { "entry": [{
                "changes": [{
                  "value": {
                    "messages": [{ "from": "919...", "id": "wamid...",
                                   "timestamp": "1700000000",
                                   "text": {"body": "hi"} }],
                    "contacts": [...]
                  }
                }]
            }] }

        Raises `ValueError` if no message is found — the webhook router
        translates that to a 400.
        """
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            message = value["messages"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(
                f"unrecognised whatsapp webhook envelope: {exc}"
            ) from exc

        external_id = _normalize_phone(str(message.get("from", "")))
        text_body: str | None = None
        if isinstance(message.get("text"), dict):
            text_body = message["text"].get("body")

        attachments: list[dict[str, Any]] = []
        for media_type in ("image", "video", "audio", "document"):
            media = message.get(media_type)
            if isinstance(media, dict) and media.get("id"):
                attachments.append({"type": media_type, **media})

        ts_raw = message.get("timestamp")
        sent_at: datetime | None
        try:
            sent_at = (
                datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
                if ts_raw
                else None
            )
        except (TypeError, ValueError):
            sent_at = None

        return InboundMessage(
            external_id=external_id,
            text=text_body,
            attachments=attachments,
            channel_message_id=str(message.get("id") or "") or None,
            sent_at=sent_at,
            raw=payload,
        )

    # --- signature / handshake --------------------------------------------

    def verify_signature(self, body: bytes, header: str | None) -> bool:
        """HMAC-SHA256 of `body` with `WHATSAPP_APP_SECRET` matches the
        `sha256=<hex>` prefix of the `X-Hub-Signature-256` header.

        Constant-time compared (no timing side channel)."""
        if not header or not header.startswith("sha256="):
            return False
        provided = header.split("=", 1)[1]
        digest = hmac.new(
            self._app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(provided, digest)

    def verify_subscription(
        self, mode: str | None, token: str | None
    ) -> bool:
        """Meta's GET-time subscription handshake."""
        return mode == "subscribe" and token == self._verify_token


async def resolve_whatsapp_adapter(
    session: AsyncSession,
) -> "WhatsAppAdapter":
    """Build a fully-configured `WhatsAppAdapter` from the active
    tenant's `Integration` row + `WhatsAppAccountConfig` sidecar.

    Relies on the ORM tenant filter from `TenantScoped` for org
    isolation — the caller must be inside a request / Celery task
    context where `app.org_id` is set. RLS authorises the read.

    Plaintext credentials (bearer token + app_secret) live only inside
    the returned adapter instance — never logged, never returned to
    any API response. The adapter falls out of scope as soon as the
    send completes, so the plaintext doesn't linger.

    Raises `WhatsAppNotConnected` if the active tenant has not
    connected WhatsApp (or has disconnected) — callers surface that
    as a 409 / `CampaignMessage.failed` rather than a generic 500."""
    from src.app.core.integrations.crypto import decrypt
    from src.app.core.integrations.whatsapp.connect import get_active_config

    bundle = await get_active_config(session)
    if bundle is None:
        raise WhatsAppNotConnected(
            "WhatsApp is not connected for this org. "
            "Connect it in Settings → Integrations."
        )
    integration, config = bundle
    return WhatsAppAdapter(
        phone_id=config.phone_id,
        token=decrypt(integration.access_token_enc),
        app_secret=decrypt(config.app_secret_enc),
        verify_token=config.verify_token,
        api_version=config.api_version,
    )


def register_default_whatsapp_adapter() -> None:
    """Wire an env-var-backed `WhatsAppAdapter` into the engine
    registry. Called once at startup from `main.py` lifespan.

    Post-Step-3.5.3, the OUTBOUND path (`conversations.send_outbound`
    + `campaigns.dispatch_chunk`) no longer goes through this
    registered factory for the `whatsapp` channel — both call sites
    short-circuit to `resolve_whatsapp_adapter(session)` which loads
    the active tenant's encrypted credentials from the DB.

    This registered adapter remains in place for the INBOUND webhook
    path (`POST /webhooks/whatsapp`), which arrives without a tenant
    context — Meta's payload identifies the target phone, not the
    target org. Migrating the webhook to per-org credentials requires
    a `phone_id → org_id` lookup in `whatsapp_account_configs`, which
    is the body of work for Step 3.5.12 (delivery webhook receiver).
    Until that lands, the webhook uses the env-var fallback (single
    Meta test app per environment)."""
    from src.app.core.conversations.models import ConversationChannel
    from src.app.core.conversations.registry import register_channel

    register_channel(
        ConversationChannel.whatsapp, lambda: WhatsAppAdapter()
    )


__all__ = [
    "WhatsAppAdapter",
    "WhatsAppNotConnected",
    "WhatsAppSendError",
    "register_default_whatsapp_adapter",
    "resolve_whatsapp_adapter",
]
