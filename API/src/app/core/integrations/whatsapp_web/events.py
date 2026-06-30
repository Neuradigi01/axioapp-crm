"""Inbound-event handlers for the WhatsApp Web (unofficial) integration.

The Node sidecar (``sidecars/whatsapp-web/``) forwards every Baileys
event to FastAPI as a HMAC-signed POST against ``/whatsapp-web/events``.
This module is the receiving end: one handler per event type, each
owning its own transaction, each tolerant of bad data (a malformed
event must never knock the receiver loop offline).

Event types handled here:

  - ``qr.updated``              → push QR data URL to SSE
  - ``connection.opened``       → mark session connected, set phone
  - ``connection.logged_out``   → mark session logged_out, expire integration
  - ``connection.reconnecting`` → mark session reconnecting (no audit)
  - ``message.received``        → translate + push through conversations
  - ``message.delivered`` /
    ``message.read`` /
    ``message.failed``          → stamp the matching message row's
                                  delivered_at / read_at columns

Handlers NEVER re-raise into the router. Failures are logged + audited;
the sidecar always receives 200 so it doesn't retry and double-persist.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations import service as conversations_service
from src.app.core.conversations.adapters import InboundMessage
from src.app.core.conversations.models import (
    ConversationChannel,
    Message,
    MessageDirection,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp_web import data_access
from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession
from src.app.core.integrations.whatsapp_web.sse_hub import hub

logger = logging.getLogger(__name__)


# --- translator helpers ----------------------------------------------------


def to_inbound_message(payload: dict[str, Any]) -> InboundMessage | None:
    """Map a canonical ``message.received`` envelope to ``InboundMessage``.

    Returns ``None`` if the envelope is structurally invalid (missing
    ``from`` or ``chat_jid``) — the handler logs + drops.
    """
    external_id = payload.get("from")
    chat_jid = payload.get("chat_jid")
    if not external_id or not chat_jid:
        return None

    message_type = payload.get("message_type", "unknown")
    text = payload.get("text")
    attachments = _attachments_from_canonical(payload)
    sent_at = _parse_timestamp(payload.get("timestamp"))

    reaction: dict[str, Any] | None = None
    if message_type == "reaction":
        r = payload.get("reaction") or {}
        if r.get("target_id"):
            reaction = {
                "target_channel_message_id": r["target_id"],
                "emoji": r.get("emoji") or "",
                "reactor_external_id": external_id,
            }

    return InboundMessage(
        external_id=str(external_id),
        text=text,
        attachments=attachments,
        channel_message_id=payload.get("provider_message_id") or None,
        sent_at=sent_at,
        raw=dict(payload.get("raw") or {}),
        reaction=reaction,
    )


def _attachments_from_canonical(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    media = payload.get("media")
    if not media or payload.get("message_type") not in {
        "image",
        "video",
        "audio",
        "document",
        "sticker",
    }:
        return []
    attachment: dict[str, Any] = {
        "type": payload["message_type"],
        "provider_message_id": payload.get("provider_message_id"),
    }
    for key in ("mime_type", "sha256", "size_bytes", "filename", "caption"):
        if key in media and media[key] is not None:
            attachment[key] = media[key]
    return [attachment]


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_group_jid(value: str | None) -> bool:
    return bool(value) and str(value).endswith("@g.us")


# --- per-event handlers ----------------------------------------------------


async def handle_qr_updated(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    qr_data_url = str(payload.get("qr_data_url") or "")
    if not qr_data_url:
        logger.warning("whatsapp_web.qr.empty_data_url")
        return

    await data_access.set_session_status(
        db,
        integration_id=session.integration_id,
        status="pairing",
        last_event_at=datetime.now(UTC),
    )
    await db.commit()

    hub.publish(
        session.integration_id,
        {
            "type": "qr_updated",
            "qr_data_url": qr_data_url,
            "status": "pairing",
        },
    )

    await audit.log(
        "integrations.whatsapp_web.qr_pushed",
        entity_type="whatsapp_web_session",
        entity_id=session.id,
    )


async def handle_connection_opened(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    phone_number = str(payload.get("phone_number") or "") or None
    await data_access.set_session_status(
        db,
        integration_id=session.integration_id,
        status="connected",
        phone_number=phone_number,
        last_event_at=datetime.now(UTC),
        last_error=None,
    )

    integration = await db.get(Integration, session.integration_id)
    if integration is not None:
        integration.status = IntegrationStatus.connected
        if phone_number:
            integration.account_label = phone_number
        integration.connected_at = datetime.now(UTC)
        integration.last_error = None
    await db.commit()

    hub.publish(
        session.integration_id,
        {
            "type": "connected",
            "status": "connected",
            "phone_number": phone_number,
        },
    )

    await audit.log(
        "integrations.whatsapp_web.connected",
        entity_type="whatsapp_web_session",
        entity_id=session.id,
        after={"phone_number": phone_number},
    )


async def handle_connection_logged_out(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    reason = str(payload.get("reason") or "loggedOut")
    await data_access.set_session_status(
        db,
        integration_id=session.integration_id,
        status="logged_out",
        last_error=reason,
        last_event_at=datetime.now(UTC),
    )

    integration = await db.get(Integration, session.integration_id)
    if integration is not None:
        integration.status = IntegrationStatus.expired
        integration.last_error = reason
    await db.commit()

    hub.publish(
        session.integration_id,
        {
            "type": "logged_out",
            "status": "logged_out",
            "reason": reason,
        },
    )

    await audit.log(
        "integrations.whatsapp_web.logged_out",
        entity_type="whatsapp_web_session",
        entity_id=session.id,
        after={"reason": reason},
    )


async def handle_connection_reconnecting(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    attempt = int(payload.get("attempt") or 1)
    await data_access.set_session_status(
        db,
        integration_id=session.integration_id,
        status="reconnecting",
        last_event_at=datetime.now(UTC),
    )
    await db.commit()

    hub.publish(
        session.integration_id,
        {
            "type": "reconnecting",
            "status": "reconnecting",
            "attempt": attempt,
        },
    )
    # Deliberately NO audit — reconnect events are frequent and noisy.


async def handle_message_received(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    chat_jid = payload.get("chat_jid")
    if is_group_jid(chat_jid):
        logger.info("whatsapp_web.message_received.group_skipped")
        return

    inbound = to_inbound_message(payload)
    if inbound is None:
        logger.warning("whatsapp_web.message_received.malformed")
        return

    try:
        await conversations_service.receive_webhook(
            db,
            channel=ConversationChannel.whatsapp,
            payload=dict(payload),
            received_via_phone_id=session.phone_number,
            pre_parsed=inbound,
        )
    except Exception:  # noqa: BLE001
        # Engine has its own commits — partial state is acceptable.
        # We log + audit; the sidecar must NOT retry on this path
        # (would create duplicates).
        logger.exception("whatsapp_web.message_received.engine_failure")
        await audit.log(
            "integrations.whatsapp_web.message_received_failed",
            entity_type="whatsapp_web_session",
            entity_id=session.id,
            after={"provider_message_id": inbound.channel_message_id},
        )


_STATUS_FIELD_BY_TYPE: dict[str, str] = {
    "message.delivered": "delivered_at",
    "message.read": "read_at",
}


async def handle_message_status(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> None:
    event_type = str(payload.get("type") or "")
    provider_message_id = payload.get("provider_message_id")
    if not provider_message_id:
        logger.warning("whatsapp_web.message_status.missing_id")
        return

    now = datetime.now(UTC)
    field = _STATUS_FIELD_BY_TYPE.get(event_type)
    if field is None and event_type != "message.failed":
        return

    stmt = select(Message).where(
        Message.channel_message_id == provider_message_id,
        Message.direction == MessageDirection.out,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        logger.info(
            "whatsapp_web.message_status.unknown_id",
            extra={"provider_message_id": provider_message_id, "type": event_type},
        )
        return

    if event_type == "message.failed":
        row.payload = {**(row.payload or {}), "delivery_status": "failed"}
        await db.commit()
        return

    update_stmt = (
        update(Message)
        .where(Message.id == row.id, getattr(Message, field).is_(None))
        .values({field: now})
    )
    await db.execute(update_stmt)
    if event_type == "message.read" and row.delivered_at is None:
        await db.execute(
            update(Message)
            .where(Message.id == row.id, Message.delivered_at.is_(None))
            .values(delivered_at=now)
        )
    await db.commit()


# --- dispatcher ------------------------------------------------------------


_HANDLERS: dict[str, Any] = {
    "qr.updated": handle_qr_updated,
    "connection.opened": handle_connection_opened,
    "connection.logged_out": handle_connection_logged_out,
    "connection.reconnecting": handle_connection_reconnecting,
    "message.received": handle_message_received,
    "message.delivered": handle_message_status,
    "message.read": handle_message_status,
    "message.failed": handle_message_status,
}


def known_event_types() -> set[str]:
    return set(_HANDLERS.keys())


async def dispatch_event(
    db: AsyncSession,
    *,
    session: WhatsAppWebSession,
    payload: dict[str, Any],
) -> bool:
    """Route ``payload`` to its handler. Returns ``True`` if a handler
    fired, ``False`` if the type was unknown. Handlers are responsible
    for their own commits and exception handling."""
    event_type = str(payload.get("type") or "")
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.info(
            "whatsapp_web.events.unknown_type",
            extra={"type": event_type},
        )
        return False
    try:
        await handler(db, session=session, payload=payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "whatsapp_web.events.handler_failed",
            extra={"type": event_type, "session_id": str(session.id)},
        )
    return True


__all__ = [
    "dispatch_event",
    "handle_connection_logged_out",
    "handle_connection_opened",
    "handle_connection_reconnecting",
    "handle_message_received",
    "handle_message_status",
    "handle_qr_updated",
    "is_group_jid",
    "known_event_types",
    "to_inbound_message",
]
