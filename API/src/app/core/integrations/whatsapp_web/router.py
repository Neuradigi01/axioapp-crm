"""HTTP routes for the WhatsApp Web (unofficial / Baileys) integration.

  POST   /api/v1/integrations/whatsapp-web/connect    → start pairing
  POST   /api/v1/integrations/whatsapp-web/disconnect → tear down
  GET    /api/v1/integrations/whatsapp-web/status     → live projection
  POST   /api/v1/integrations/whatsapp-web/events     → sidecar inbound (HMAC-only)
  GET    /api/v1/integrations/whatsapp-web/qr-stream  → SSE for QR + status

Connect / disconnect / status / qr-stream gate on
``settings.integrations.manage``. ``/events`` is the only public route
on this surface — it carries the sidecar's HMAC-SHA256 signature in
``X-Fastapi-Signature`` and that IS the auth.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import WHATSAPP_WEB_INBOUND_HMAC_SECRET
from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp_web import data_access, events, service
from src.app.core.integrations.whatsapp_web.exceptions import (
    AlreadyConnected,
    SidecarUnavailable,
)
from src.app.core.integrations.whatsapp_web.schemas import WhatsAppWebSessionOut
from src.app.core.integrations.whatsapp_web.sse_hub import hub
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, get_context, set_context
from src.app.shared.db import get_db

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_S = 15.0
_SSE_MAX_LIFETIME_S = 5 * 60.0


router = APIRouter(
    prefix="/whatsapp-web",
    tags=["Integrations · WhatsApp Web"],
)


@router.post(
    "/connect",
    response_model=WhatsAppWebSessionOut,
    status_code=status.HTTP_200_OK,
)
async def connect_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> WhatsAppWebSessionOut:
    """Start a WhatsApp Web pairing flow for the active organisation.

    Returns the freshly-created session in ``status='pairing'``. The
    QR data URL is *not* on this response — it's delivered via the
    Step-6 SSE stream once the sidecar produces it.

    Errors:
      - 409 if the org already has an active Web session.
      - 502 if the sidecar is unreachable. The session row is left
        in ``status='error'`` with ``last_error`` populated.
    """
    try:
        return await service.connect_session(db, actor_id=user.legacy_uuid)
    except AlreadyConnected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": str(exc),
                "hint": "POST /api/v1/integrations/whatsapp-web/disconnect first.",
            },
        ) from exc
    except SidecarUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "WhatsApp Web sidecar unavailable. The integration row was "
                "marked as 'error'; retry the connect once the sidecar is "
                f"reachable. ({exc.detail})"
            ),
        ) from exc


@router.post(
    "/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> Response:
    """Disconnect the org's WhatsApp Web pairing.

    Tolerant of sidecar downtime — local rows are cleaned up even if
    the sidecar DELETE 502s. Returns 204 on success, 404 if the org
    has no WhatsApp Web integration to disconnect.
    """
    removed = await service.disconnect_session(db, actor_id=user.legacy_uuid)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No WhatsApp Web integration found for this organisation.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/status",
    response_model=WhatsAppWebSessionOut | None,
)
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> WhatsAppWebSessionOut | None:
    """Live status projection. Returns ``null`` if the org has never
    paired WhatsApp Web. Triggers a best-effort sidecar refresh when
    the cached row is older than 60s and still marked ``connected``."""
    return await service.get_status(db)


# --- public events receiver (HMAC-only, no JWT) ----------------------------


def _verify_inbound_signature(raw: bytes, header: str | None) -> bool:
    secret = WHATSAPP_WEB_INBOUND_HMAC_SECRET
    if not secret:
        # Mismatched env: refuse all events rather than silently accept
        # — operator notices on the very first sidecar -> FastAPI hop.
        logger.error(
            "whatsapp_web.events.inbound_secret_empty — "
            "WHATSAPP_WEB_INBOUND_HMAC_SECRET is not set"
        )
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = (
        "sha256="
        + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, header)


@router.post(
    "/events",
    include_in_schema=False,
    status_code=status.HTTP_200_OK,
)
async def events_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Sidecar → FastAPI event ingest. HMAC-only; no JWT.

    Returns 200 with ``{"ok": true}`` on accepted events (handler failures
    are swallowed internally to keep the sidecar from retrying), 401 on
    bad signature, 404 when the ``session_id`` in the body is unknown.
    """
    raw = await request.body()
    if not _verify_inbound_signature(raw, request.headers.get("x-fastapi-signature")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    try:
        payload: dict[str, Any] = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid JSON body",
        ) from exc

    sidecar_session_id = payload.get("session_id")
    if not isinstance(sidecar_session_id, str) or not sidecar_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing session_id",
        )

    session_row = await data_access.get_session_by_sidecar_id(
        db, sidecar_session_id=sidecar_session_id
    )
    if session_row is None:
        # Sidecar drops on 4xx (per Step 3's forwarder design) so this
        # is the right code: there is no such session on our side.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    # Set tenant context so RLS applies to subsequent DB writes inside
    # the handlers. The bare bytes signature is already verified, so we
    # trust the ``org_id`` only insofar as it matches the session row's
    # stored org_id — never read the org from the body directly.
    set_context(RequestContext(org_id=session_row.org_id, user_id=None))

    handled = await events.dispatch_event(db, session=session_row, payload=payload)
    return {"ok": True, "handled": handled}


# --- SSE stream for the SPA -----------------------------------------------


def _sse_format(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent-Event frame."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _qr_stream_generator(
    integration_id: Any,
    initial_state: dict[str, Any] | None,
) -> AsyncIterator[bytes]:
    """Stream pairing state to the SPA.

    Yields:
      - one ``initial`` frame with whatever DB state the request found,
      - every ``hub`` publish for this integration,
      - a ``: ping`` heartbeat every ``_HEARTBEAT_INTERVAL_S`` seconds.

    Closes when the client disconnects or after ``_SSE_MAX_LIFETIME_S``
    of total stream time (defends against zombie connections holding
    queues open through proxies).
    """
    if initial_state is not None:
        yield _sse_format("state", initial_state).encode("utf-8")

    sub = hub.subscribe(integration_id)
    started_at = asyncio.get_running_loop().time()
    try:
        while True:
            if asyncio.get_running_loop().time() - started_at > _SSE_MAX_LIFETIME_S:
                return
            try:
                payload = await asyncio.wait_for(
                    sub.__anext__(), timeout=_HEARTBEAT_INTERVAL_S
                )
            except asyncio.TimeoutError:
                yield b": ping\n\n"
                continue
            except StopAsyncIteration:
                return
            event_type = str(payload.get("type") or "message")
            yield _sse_format(event_type, payload).encode("utf-8")
    finally:
        await sub.aclose()


@router.get(
    "/qr-stream",
    include_in_schema=False,
)
async def qr_stream_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> StreamingResponse:
    """Server-Sent-Events stream for the pairing UI.

    Emits ``event: state`` once on connect (cached row), then every
    ``hub.publish`` for this org's integration. Heartbeat every 15s so
    proxies don't close the connection during a long QR wait. Closes
    after 5 minutes of stream lifetime — the SPA reconnects."""
    from src.app.core.integrations import data_access as integrations_dal
    from src.app.core.integrations.models import IntegrationProvider

    org_id = get_context().org_id
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="tenant context missing",
        )

    integration = await integrations_dal.find_integration_for_org_provider(
        db, org_id=org_id, provider=IntegrationProvider.whatsapp_web
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No WhatsApp Web integration found for this organisation.",
        )

    session_row = await data_access.get_session_by_integration(
        db, integration_id=integration.id
    )
    initial: dict[str, Any] = {
        "type": "state",
        "status": session_row.status if session_row is not None else "pending",
        "phone_number": (
            session_row.phone_number if session_row is not None else None
        ),
    }

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _qr_stream_generator(integration.id, initial),
        media_type="text/event-stream",
        headers=headers,
    )
