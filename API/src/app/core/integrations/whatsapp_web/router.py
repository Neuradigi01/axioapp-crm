"""HTTP routes for the WhatsApp Web (unofficial / Baileys) integration.

  POST   /api/v1/integrations/whatsapp-web/connect    → start pairing
  POST   /api/v1/integrations/whatsapp-web/disconnect → tear down
  GET    /api/v1/integrations/whatsapp-web/status     → live projection

Connect / disconnect gate on ``settings.integrations.manage``; status
is readable by anyone with that permission too (no read-only role
distinction in this surface for v1). Step 6 will add the public
events receiver + SSE QR stream on the same router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp_web import service
from src.app.core.integrations.whatsapp_web.exceptions import (
    AlreadyConnected,
    SidecarUnavailable,
)
from src.app.core.integrations.whatsapp_web.schemas import WhatsAppWebSessionOut
from src.app.core.users.models import User
from src.app.shared.db import get_db


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
