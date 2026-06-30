"""Service layer for the WhatsApp Web (unofficial / Baileys) integration.

Owns:
  - ``connect_session`` — start a pairing flow (one Integration row +
    one WhatsAppWebSession row, then a sidecar call).
  - ``disconnect_session`` — tear both sides down. Tolerant of sidecar
    downtime: local cleanup runs even if the sidecar 502s.
  - ``get_status`` — best-effort live status projection. Triggers a
    liveness refresh against the sidecar when the cached row is stale.

Per the layered-architecture rule, this is the only layer that owns
transactions for this module. The DAL never commits.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations import data_access as integrations_dal
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.whatsapp_web import data_access
from src.app.core.integrations.whatsapp_web.exceptions import (
    AlreadyConnected,
    SidecarUnavailable,
)
from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession
from src.app.core.integrations.whatsapp_web.schemas import (
    WhatsAppWebSessionOut,
    WhatsAppWebStatus,
)
from src.app.core.integrations.whatsapp_web.sidecar_client import SidecarClient
from src.app.core.integrations.whatsapp_web.sse_hub import hub as _sse_hub
from src.app.shared.context import get_context

logger = logging.getLogger(__name__)

_LIVENESS_REFRESH_SECONDS = 60


def _new_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


def _to_view(row: WhatsAppWebSession) -> WhatsAppWebSessionOut:
    return WhatsAppWebSessionOut.model_validate(row)


def _current_org_id() -> uuid.UUID:
    ctx = get_context()
    if ctx.org_id is None:
        raise RuntimeError("tenant context missing (no org_id)")
    return ctx.org_id


async def connect_session(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    client: SidecarClient | None = None,
) -> WhatsAppWebSessionOut:
    """Start a WhatsApp Web pairing flow.

    Sequence:
      1. Reject if an integration row for ``whatsapp_web`` already
         exists with ``status='connected'`` (caller must disconnect
         first). The ``pairing`` in-flight state is *idempotent* — a
         second connect returns the existing session.
      2. Upsert the ``Integration`` row (provider=whatsapp_web,
         status=disconnected until the sidecar acks).
      3. Mint a fresh ``sidecar_session_id`` (uuid4 hex).
      4. Upsert the ``WhatsAppWebSession`` row with ``status='pending'``.
      5. ``db.flush()`` — guarantees the rows exist for any later
         query inside this transaction.
      6. Call the sidecar's ``POST /sessions``. On failure: mark the
         session row ``error`` + persist ``last_error`` + commit, then
         re-raise so the router returns 502.
      7. On success: mark the session row ``pairing`` + commit.
      8. Audit + return the projection.
    """
    org_id = _current_org_id()
    sidecar = client or SidecarClient()

    existing_integration = await integrations_dal.find_integration_for_org_provider(
        db, org_id=org_id, provider=IntegrationProvider.whatsapp_web
    )

    if (
        existing_integration is not None
        and existing_integration.status == IntegrationStatus.connected
    ):
        existing_session = await data_access.get_session_by_integration(
            db, integration_id=existing_integration.id
        )
        if existing_session is not None and existing_session.status not in (
            "disconnected",
            "logged_out",
            "error",
        ):
            raise AlreadyConnected(
                "WhatsApp Web is already paired for this organisation. "
                "Disconnect first to re-pair."
            )

    now = datetime.now(UTC)

    if existing_integration is None:
        integration = Integration(
            org_id=org_id,
            provider=IntegrationProvider.whatsapp_web,
            status=IntegrationStatus.disconnected,
            connected_by=actor_id,
            connected_at=now,
            webhook_secret=_new_webhook_secret(),
        )
        db.add(integration)
    else:
        integration = existing_integration
        integration.status = IntegrationStatus.disconnected
        integration.connected_by = actor_id
        integration.connected_at = now
        integration.disconnected_at = None
        integration.disconnected_by = None
        integration.last_error = None
        if integration.webhook_secret is None:
            integration.webhook_secret = _new_webhook_secret()

    await db.flush()

    sidecar_session_id = uuid.uuid4().hex
    session_row = await data_access.upsert_session(
        db,
        org_id=org_id,
        integration_id=integration.id,
        sidecar_session_id=sidecar_session_id,
        status="pending",
        phone_number=None,
        last_error=None,
        last_event_at=None,
    )
    await db.flush()

    try:
        await sidecar.create_session(
            org_id=str(org_id), sidecar_session_id=sidecar_session_id
        )
    except SidecarUnavailable as exc:
        session_row.status = "error"
        session_row.last_error = exc.detail[:255]
        session_row.last_event_at = datetime.now(UTC)
        integration.last_error = exc.detail[:255]
        await db.commit()
        await db.refresh(session_row)
        logger.warning(
            "whatsapp_web.connect.sidecar_unavailable",
            extra={"err": exc.detail, "org_id": str(org_id)},
        )
        raise

    session_row.status = "pairing"
    session_row.last_event_at = datetime.now(UTC)
    integration.status = IntegrationStatus.connected
    integration.last_error = None
    await db.commit()
    await db.refresh(session_row)

    # Push an immediate "pairing" frame so the SPA's EventSource
    # (Step 6) shows state before the first sidecar event arrives.
    _sse_hub.publish(
        integration.id,
        {"type": "pairing", "status": "pairing"},
    )

    await audit.log(
        "integrations.whatsapp_web.connect_initiated",
        entity_type="whatsapp_web_session",
        entity_id=session_row.id,
        after={"integration_id": str(integration.id)},
    )
    return _to_view(session_row)


async def disconnect_session(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    client: SidecarClient | None = None,
) -> bool:
    """Tear down the org's WhatsApp Web pairing.

    Tolerant of sidecar downtime: the local rows are always cleaned
    up regardless of whether the sidecar accepts the DELETE. Returns
    ``False`` if there was nothing to disconnect (router maps to 404).
    """
    org_id = _current_org_id()
    sidecar = client or SidecarClient()

    integration = await integrations_dal.find_integration_for_org_provider(
        db, org_id=org_id, provider=IntegrationProvider.whatsapp_web
    )
    if integration is None:
        return False
    session_row = await data_access.get_session_by_integration(
        db, integration_id=integration.id
    )

    if session_row is not None:
        try:
            await sidecar.delete_session(
                sidecar_session_id=session_row.sidecar_session_id
            )
        except SidecarUnavailable as exc:
            logger.warning(
                "whatsapp_web.disconnect.sidecar_unavailable",
                extra={"err": exc.detail, "org_id": str(org_id)},
            )

        session_row.status = "disconnected"
        session_row.phone_number = None
        session_row.last_event_at = datetime.now(UTC)
        session_row.last_error = None

    now = datetime.now(UTC)
    integration.status = IntegrationStatus.disconnected
    integration.disconnected_at = now
    integration.disconnected_by = actor_id

    await db.commit()

    await audit.log(
        "integrations.whatsapp_web.disconnected",
        entity_type="integration",
        entity_id=integration.id,
    )
    return True


async def get_status(
    db: AsyncSession,
    *,
    client: SidecarClient | None = None,
) -> Optional[WhatsAppWebSessionOut]:
    """Return the live status projection for the active tenant, or
    ``None`` if no WhatsApp Web integration exists.

    Triggers a best-effort sidecar refresh when the cached row is
    older than ``_LIVENESS_REFRESH_SECONDS`` and still marked
    ``connected`` — keeps the SPA honest if events were missed.
    """
    org_id = _current_org_id()

    integration = await integrations_dal.find_integration_for_org_provider(
        db, org_id=org_id, provider=IntegrationProvider.whatsapp_web
    )
    if integration is None:
        return None

    session_row = await data_access.get_session_by_integration(
        db, integration_id=integration.id
    )
    if session_row is None:
        return None

    now = datetime.now(UTC)
    if (
        session_row.status == "connected"
        and session_row.last_event_at is not None
        and (now - session_row.last_event_at).total_seconds()
        > _LIVENESS_REFRESH_SECONDS
    ):
        sidecar = client or SidecarClient()
        try:
            live = await sidecar.get_session(
                sidecar_session_id=session_row.sidecar_session_id
            )
        except SidecarUnavailable as exc:
            logger.info(
                "whatsapp_web.status.liveness_refresh_failed",
                extra={"err": exc.detail, "org_id": str(org_id)},
            )
        else:
            if live is not None:
                mapped = _map_sidecar_status(live.get("status"))
                if mapped is not None and mapped != session_row.status:
                    session_row.status = mapped
                phone = live.get("phone_number")
                if phone:
                    session_row.phone_number = phone
                session_row.last_event_at = now
                await db.commit()
                await db.refresh(session_row)

    return _to_view(session_row)


def _map_sidecar_status(value: object) -> Optional[str]:
    """Map the sidecar's session status string to our canonical set.
    Unknown / missing values map to ``None`` (no update)."""
    if not isinstance(value, str):
        return None
    if value in {s.value for s in WhatsAppWebStatus}:
        return value
    return None


__all__ = [
    "connect_session",
    "disconnect_session",
    "get_status",
]
