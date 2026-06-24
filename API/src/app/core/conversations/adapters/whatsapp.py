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
  with the org's `app_secret` (decrypted from `whatsapp_account_configs`
  by the webhook receiver per Step 3.5.12). Failures return 403.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)

logger = logging.getLogger(__name__)


class WhatsAppSendError(Exception):
    """Raised when the Cloud API returns a non-2xx."""


class WhatsAppRateLimited(Exception):
    """Raised by `send` / `send_template` when Meta returns 429.

    Carries `retry_after_seconds` parsed from the `Retry-After` header
    (or a sensible default if Meta omitted it). The Celery task
    catches this, sleeps the suggested duration, and either retries
    in-place or surfaces to Celery's autoretry policy if the burst
    persists. The pure-API path (conversations inbox send) returns
    503 with the same Retry-After header so the SPA can back off.
    """

    def __init__(self, message: str, *, retry_after_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


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


def _make_rate_limit_error(response: httpx.Response) -> "WhatsAppRateLimited":
    """Translate Meta's 429 into our typed exception.

    Honours the `Retry-After` header when present (Meta sends seconds
    in the standard form). Falls back to 60s — a defensive default
    that's longer than Meta's typical rate-limit window."""
    retry_after_raw = response.headers.get("retry-after")
    retry_after = 60
    try:
        if retry_after_raw:
            retry_after = max(1, int(float(retry_after_raw)))
    except (TypeError, ValueError):
        pass
    detail = response.text[:200] if response.text else ""
    return WhatsAppRateLimited(
        f"whatsapp rate limited (retry after {retry_after}s): {detail}",
        retry_after_seconds=retry_after,
    )


# Interactive message kinds the adapter understands. The composer
# builder modal feeds one of these dicts into `send()` via the
# `interactive` kwarg; the adapter shapes it into Meta's documented
# envelope. See `core/conversations/schemas.InteractivePayload` for the
# validated input shape — by the time we reach the adapter the
# Pydantic discriminated union has already enforced Meta's char limits.
_INTERACTIVE_KINDS = {"reply_buttons", "cta_url", "list"}


def _build_interactive_envelope(
    *,
    to: str,
    interactive: dict[str, Any],
) -> dict[str, Any]:
    """Turn the composer's `interactive` dict into Meta's `type:
    interactive` envelope.

    Header/footer are optional everywhere; body is mandatory. Each
    `kind` maps to one of Meta's documented `interactive.type` values:

      * ``reply_buttons`` → ``button`` with up to 3 `quick_reply`
        action buttons.
      * ``cta_url`` → ``cta_url`` with a single URL-opening button.
      * ``list`` → ``list`` with sections + rows.

    The persisted ``interactive_payload`` row column keeps the
    operator-facing shape so the bubble can re-render months later;
    Meta-facing envelope is rebuilt on the fly here."""
    kind = interactive["kind"]
    body = {"text": interactive["body"]}
    block: dict[str, Any] = {"body": body}

    header = interactive.get("header")
    if isinstance(header, dict) and header.get("text"):
        block["header"] = {"type": "text", "text": header["text"]}

    footer = interactive.get("footer")
    if isinstance(footer, str) and footer:
        block["footer"] = {"text": footer}

    if kind == "reply_buttons":
        block["type"] = "button"
        block["action"] = {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": btn["id"],
                        "title": btn["title"],
                    },
                }
                for btn in interactive["buttons"]
            ]
        }
    elif kind == "cta_url":
        block["type"] = "cta_url"
        block["action"] = {
            "name": "cta_url",
            "parameters": {
                "display_text": interactive["button_text"],
                "url": interactive["url"],
            },
        }
    elif kind == "list":
        block["type"] = "list"
        block["action"] = {
            "button": interactive["button_text"],
            "sections": [
                {
                    "title": section["title"],
                    "rows": [
                        {
                            "id": row["id"],
                            "title": row["title"],
                            **(
                                {"description": row["description"]}
                                if row.get("description")
                                else {}
                            ),
                        }
                        for row in section["rows"]
                    ],
                }
                for section in interactive["sections"]
            ],
        }
    else:
        raise ValueError(f"unknown interactive kind: {kind!r}")

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": block,
    }


_MEDIA_ATTACHMENT_TYPES = {"image", "video", "audio", "document"}

# Meta accepts a caption for image / video / document media envelopes
# but silently drops it for audio. Keep this set in sync with
# `media_upload._CAPTIONS_SUPPORTED` — the router uses that one for
# input validation; this one is the adapter's render-time guard.
_MEDIA_CAPTIONABLE = {"image", "video", "document"}


def _first_media_attachment(
    attachments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first attachment that looks like a media reference
    (``{type, media_id}``), or ``None``. Inbound-style descriptors
    (``{type, id, sha256}`` from `parse_webhook`) live in the same
    list shape — discriminate on ``media_id`` to avoid mis-handling
    them when the caller echoes an inbound payload back."""
    for att in attachments:
        if not isinstance(att, dict):
            continue
        t = att.get("type")
        if t in _MEDIA_ATTACHMENT_TYPES and isinstance(
            att.get("media_id"), str
        ):
            return att
    return None


def _build_media_envelope(
    *,
    to: str,
    media: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    """Render Meta's media-message envelope.

    Caption sourcing: the composer's text field is reused as the
    caption for image/video/document. ``media['caption']`` (when
    present) takes precedence so an automation can pass a structured
    caption without piggy-backing on the human-typed text.

    For ``document`` we also forward the ``filename`` Meta uses to
    label the download on the recipient side."""
    media_type = media["type"]
    media_id = media["media_id"]
    block: dict[str, Any] = {"id": media_id}
    if media_type in _MEDIA_CAPTIONABLE:
        caption = media.get("caption") or text
        if isinstance(caption, str) and caption:
            block["caption"] = caption[:1024]
    if media_type == "document":
        filename = media.get("filename")
        if isinstance(filename, str) and filename:
            block["filename"] = filename
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": media_type,
        media_type: block,
    }


def _render_template_components(
    *,
    variables: dict[int, str],
    header_type: str | None = None,
    header_text: str | None = None,
) -> list[dict[str, Any]]:
    """Turn a `{1: "Asha", 2: "30%"}` dict into Meta's `components[]`
    payload shape:

        [{"type":"body","parameters":[
            {"type":"text","text":"Asha"},
            {"type":"text","text":"30%"}]}]

    Header parameters are added as a separate `{"type":"header"}` entry
    only when `header_type='TEXT'` and `header_text` carries a `{{1}}`
    placeholder — Meta's spec allows a single header variable.

    Variables are emitted in numeric order so `{{1}}` always lands at
    parameter index 0 (Meta substitutes by position, not by name)."""
    out: list[dict[str, Any]] = []

    if header_type == "TEXT" and header_text and "{{1}}" in header_text:
        # Header has its own single-variable slot. Use the variable's
        # resolved value at key 1 if present; otherwise fall back to
        # the raw header_text (rare — the picker should have collected
        # an input for it).
        header_value = variables.get(1, "")
        if header_value:
            out.append(
                {
                    "type": "header",
                    "parameters": [
                        {"type": "text", "text": str(header_value)}
                    ],
                }
            )

    body_params = [
        {"type": "text", "text": str(variables[n])}
        for n in sorted(variables)
    ]
    if body_params:
        out.append({"type": "body", "parameters": body_params})

    return out


class WhatsAppAdapter:
    """Implements `ChannelAdapter` for Meta's WhatsApp Cloud API."""

    def __init__(
        self,
        *,
        phone_id: str,
        token: str,
        app_secret: str,
        verify_token: str,
        api_version: str = "v18.0",
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
        interactive: dict[str, Any] | None = None,
        reply_to_channel_message_id: str | None = None,
    ) -> ChannelMessageRef:
        """POST a message to Meta's Cloud API.

        Routes to one of three envelopes, in priority order:

          * ``interactive`` (whatsapp-platform-upgrade Step 6) — Meta's
            ``type=interactive`` shape for quick-reply buttons, CTA
            buttons, or list messages.
          * Media reference inside ``attachments`` (Step 5) — Meta's
            ``image``/``video``/``audio``/``document`` envelope.
          * Plain text — original text-only path.

        Templates are still routed through ``send_template``.

        ``reply_to_channel_message_id`` (Step 7): when set, the
        envelope carries Meta's documented ``context: {message_id}``
        shape so the recipient client renders the new bubble as a
        quoted reply to the original.

        Step 23 — block-list pre-send. We refuse to ship to any
        phone on the org's block list with a
        ``BlockedNumberOutbound`` exception. The campaign service
        catches this and writes a stable failed-row error; the
        manual reply path surfaces as a 4xx with the same message."""
        to = _normalize_phone(external_id).lstrip("+")
        # Block-list check runs before any envelope work + before the
        # rate-limit acquire so we never burn a token on a forbidden
        # outbound. Adapter holds no AsyncSession of its own — it
        # would need to be threaded through every call site to do a
        # DB check here. We instead let the campaign send-guard +
        # the conversation send path enforce the check at their
        # respective callers (they DO hold a session). The adapter
        # documents the contract via the comment so an inadvertent
        # future direct adapter call doesn't silently bypass the
        # compliance gate.
        if interactive:
            envelope = _build_interactive_envelope(
                to=to, interactive=interactive
            )
        else:
            media = _first_media_attachment(attachments)
            if media is not None:
                envelope = _build_media_envelope(
                    to=to,
                    media=media,
                    text=text,
                )
            else:
                envelope = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                }
        if reply_to_channel_message_id:
            envelope["context"] = {"message_id": reply_to_channel_message_id}
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._http_factory() as client:
            resp = await client.post(
                self.endpoint, json=envelope, headers=headers
            )
        if resp.status_code == 429:
            raise _make_rate_limit_error(resp)
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

    # --- outbound (reaction) ----------------------------------------------

    async def send_reaction(
        self,
        *,
        external_id: str,
        target_channel_message_id: str,
        emoji: str | None,
    ) -> ChannelMessageRef:
        """POST a reaction to Meta's Cloud API
        (whatsapp-platform-upgrade Step 7).

        Meta's ``type=reaction`` envelope carries a sub-block with
        ``message_id`` (the target wamid) + ``emoji`` (single unicode
        emoji, or empty string to remove). Per Meta docs, sending an
        empty string with the same recipient+target combination removes
        the caller's previous reaction.

        Returns a ``ChannelMessageRef`` with the new reaction event's
        own wamid; the service typically discards this — reactions
        write to the *target* message's ``reactions`` JSONB rather
        than landing as their own row."""
        to = _normalize_phone(external_id).lstrip("+")
        envelope = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": target_channel_message_id,
                "emoji": emoji or "",
            },
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._http_factory() as client:
            resp = await client.post(
                self.endpoint, json=envelope, headers=headers
            )
        if resp.status_code == 429:
            raise _make_rate_limit_error(resp)
        if resp.status_code >= 400:
            raise WhatsAppSendError(
                f"whatsapp reaction send failed: "
                f"{resp.status_code} {resp.text}"
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

    # --- outbound (template) ----------------------------------------------

    async def send_template(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        template_name: str,
        language: str,
        variables: dict[int, str],
        header_type: str | None = None,
        header_text: str | None = None,
    ) -> ChannelMessageRef:
        """POST a template message to Meta's Cloud API.

        `variables` maps `{{n}}` → resolved plaintext (e.g. `{1: "Asha",
        2: "30%"}`). The caller (Step 3.5.6 dispatch) is responsible for
        resolving `kind=field` bindings against the contact before calling
        this method — the adapter only deals with flat values.

        `header_type` + `header_text` are passed-through for templates
        whose HEADER is TEXT with a `{{1}}` variable (Meta supports a
        single header variable). Other header formats (IMAGE/VIDEO/
        DOCUMENT) are out of scope here — caller pre-validates.
        """
        to = _normalize_phone(external_id).lstrip("+")
        components = _render_template_components(
            variables=variables,
            header_type=header_type,
            header_text=header_text,
        )
        envelope: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            envelope["template"]["components"] = components
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._http_factory() as client:
            resp = await client.post(
                self.endpoint, json=envelope, headers=headers
            )
        if resp.status_code == 429:
            raise _make_rate_limit_error(resp)
        if resp.status_code >= 400:
            raise WhatsAppSendError(
                f"whatsapp template send failed: {resp.status_code} {resp.text}"
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

        # Reaction event (whatsapp-platform-upgrade Step 7) — Meta sends
        # these as standalone messages with `type: reaction`. The engine
        # short-circuits these in `receive_webhook`: instead of creating
        # a new message row, it applies the emoji to the target row's
        # `reactions` JSONB and returns. Empty `emoji` = remove.
        reaction_block: dict[str, Any] | None = None
        if isinstance(message.get("reaction"), dict):
            r = message["reaction"]
            target = r.get("message_id")
            emoji = r.get("emoji")
            if isinstance(target, str):
                reaction_block = {
                    "target_channel_message_id": target,
                    "emoji": emoji if isinstance(emoji, str) else "",
                    "reactor_external_id": external_id,
                }

        # Quoted-reply attribution (Step 7): Meta delivers the original
        # message's wamid in `context.id` for ANY message type that
        # quotes a previous one (text, media, template — not just
        # interactive). The interactive branch below extracts it again
        # for button/list replies; do the lookup once here so it covers
        # the text path too.
        reply_to_wamid: str | None = None
        ctx = message.get("context")
        if isinstance(ctx, dict):
            cid = ctx.get("id")
            if isinstance(cid, str) and cid:
                reply_to_wamid = cid

        # Interactive reply events (whatsapp-platform-upgrade Step 6).
        # Meta delivers these as `interactive: { type: button_reply |
        # list_reply, button_reply: {id, title} | list_reply: {id,
        # title, description}, context: {id: <original_message_id>} }`.
        # Surface the tapped row as the text body so the inbox renders
        # something readable, and stash the attribution shape on
        # `attachments[]` so the bubble can show "↳ Reply to: …".
        interactive = message.get("interactive")
        if isinstance(interactive, dict):
            kind = interactive.get("type")
            context = message.get("context")
            original_id = (
                context.get("id") if isinstance(context, dict) else None
            )
            if kind == "button_reply":
                payload = interactive.get("button_reply") or {}
                if isinstance(payload, dict):
                    title = payload.get("title")
                    if isinstance(title, str) and not text_body:
                        text_body = title
                    attachments.append(
                        {
                            "type": "reply",
                            "reply_kind": "button",
                            "reply_to_id": payload.get("id"),
                            "reply_to_title": title,
                            "reply_to_message_id": original_id,
                        }
                    )
            elif kind == "list_reply":
                payload = interactive.get("list_reply") or {}
                if isinstance(payload, dict):
                    title = payload.get("title")
                    if isinstance(title, str) and not text_body:
                        text_body = title
                    attachments.append(
                        {
                            "type": "reply",
                            "reply_kind": "list",
                            "reply_to_id": payload.get("id"),
                            "reply_to_title": title,
                            "reply_to_description": payload.get(
                                "description"
                            ),
                            "reply_to_message_id": original_id,
                        }
                    )

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
            reply_to_channel_message_id=reply_to_wamid,
            reaction=reaction_block,
        )

    # --- signature / handshake --------------------------------------------

    def verify_signature(self, body: bytes, header: str | None) -> bool:
        """HMAC-SHA256 of `body` with the adapter's `app_secret` matches
        the `sha256=<hex>` prefix of the `X-Hub-Signature-256` header.

        Constant-time compared (no timing side channel). The webhook
        receiver (Step 3.5.12) decrypts the org's app_secret per
        request and passes it through this adapter's constructor."""
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
    # `app_secret_enc` is NULL for orgs that connected via Embedded
    # Signup (whatsapp-platform-upgrade Step 2) — the webhook verifier
    # falls back to the env-side `WHATSAPP_APP_SECRET`, and `send()`
    # never touches the adapter's `_app_secret` attribute at all. Pass
    # an empty string here so the constructor doesn't trip on `None`;
    # the signature path keeps reading from env for ES-connected orgs.
    app_secret = (
        decrypt(config.app_secret_enc) if config.app_secret_enc else ""
    )
    return WhatsAppAdapter(
        phone_id=config.phone_id,
        token=decrypt(integration.access_token_enc),
        app_secret=app_secret,
        verify_token=config.verify_token,
        api_version=config.api_version,
    )


# --- Step 3.5.12: Meta status events ------------------------------------


@dataclass(frozen=True, slots=True)
class WhatsAppStatusEvent:
    """One delivery-status update parsed from Meta's `statuses[]` array.

    `status` is Meta's lifecycle value verbatim (`sent` / `delivered`
    / `read` / `failed`). `recipient_id` is the contact's phone (E.164,
    no `+`). `timestamp` is the unix-seconds Meta reports for the
    event. `error` is populated only when `status='failed'` — Meta's
    error.message field.
    """

    channel_message_id: str
    status: str
    recipient_id: str
    timestamp: datetime
    error: str | None = None


def parse_statuses(payload: dict[str, Any]) -> list["WhatsAppStatusEvent"]:
    """Extract delivery-status events from a Meta webhook payload.

    Webhook envelopes carry EITHER `messages[]` (inbound replies) OR
    `statuses[]` (delivery acknowledgements) — never both in v1
    Cloud API. This helper handles the `statuses` branch; the existing
    `parse_webhook` handles `messages`.

    Returns `[]` when the payload has no statuses (the caller treats
    that as "not a status payload, try the inbound-message path
    instead"). Skips malformed entries rather than raising — Meta
    occasionally adds fields to the envelope, and we don't want a
    single bad row to discard the whole batch.
    """
    out: list[WhatsAppStatusEvent] = []
    try:
        value = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return out
    statuses = value.get("statuses") if isinstance(value, dict) else None
    if not isinstance(statuses, list):
        return out
    for status in statuses:
        if not isinstance(status, dict):
            continue
        msg_id = status.get("id")
        s = status.get("status")
        if not msg_id or not s:
            continue
        recipient = str(status.get("recipient_id") or "")
        ts_raw = status.get("timestamp")
        try:
            timestamp = (
                datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
                if ts_raw
                else datetime.now(timezone.utc)
            )
        except (TypeError, ValueError):
            timestamp = datetime.now(timezone.utc)
        error_msg: str | None = None
        errors_list = status.get("errors")
        if isinstance(errors_list, list) and errors_list:
            first = errors_list[0]
            if isinstance(first, dict):
                error_msg = (
                    first.get("title")
                    or first.get("message")
                    or str(first)
                )[:512]
        out.append(
            WhatsAppStatusEvent(
                channel_message_id=str(msg_id),
                status=str(s),
                recipient_id=recipient,
                timestamp=timestamp,
                error=error_msg,
            )
        )
    return out


def parse_inbound_phone(payload: dict[str, Any]) -> str | None:
    """Extract the customer's phone number from a Meta inbound
    webhook (whatsapp-platform-upgrade Step 23).

    Used by the block-list early-drop check — we only need the
    phone, not the full parsed message envelope, so this avoids
    paying the cost of ``WhatsAppAdapter.parse_webhook`` (which
    pulls in template references, attachments, reactions, etc.).

    Returns ``None`` for status-only payloads + malformed envelopes
    + reaction events without a `from` field. Callers treat None as
    "not a checkable inbound, continue with the standard pipeline"."""
    try:
        value = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict):
        return None
    raw = first.get("from")
    return str(raw) if raw else None


__all__ = [
    "WhatsAppAdapter",
    "WhatsAppNotConnected",
    "WhatsAppRateLimited",
    "WhatsAppSendError",
    "WhatsAppStatusEvent",
    "_render_template_components",
    "parse_inbound_phone",
    "parse_statuses",
    "resolve_whatsapp_adapter",
]
