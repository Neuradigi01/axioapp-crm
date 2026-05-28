"""HTTP routes for the WhatsApp Business Account connect surface.

  POST /api/v1/integrations/whatsapp/connect      → validate + store
  POST /api/v1/integrations/whatsapp/disconnect   → null token + status
  POST /api/v1/integrations/whatsapp/test         → ping Meta now
  GET  /api/v1/integrations/whatsapp/status       → projection (no creds)

All endpoints gate on `settings.integrations.manage` — Owner-only by
default, same as the rest of the integrations surface. Encrypted-
credential columns NEVER appear in any response body (the schemas don't
declare them; the connect service returns the projection from
`get_status`, which has no token fields).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp.connect import (
    MetaValidationError,
    connect_account,
    disconnect_account,
    get_status,
    test_connection,
)
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppConnectIn,
    WhatsAppStatusOut,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(
    prefix="/whatsapp", tags=["Integrations · WhatsApp"]
)


@router.post("/connect", response_model=WhatsAppStatusOut)
async def connect_endpoint(
    payload: WhatsAppConnectIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> WhatsAppStatusOut:
    """Validate the operator-supplied credentials against Meta, then
    persist (encrypted) on success. 400 with Meta's error message on
    rejection."""
    try:
        projection = await connect_account(
            db,
            org_id=user.org_id,
            actor_id=user.legacy_uuid,
            payload=payload,
        )
    except MetaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return WhatsAppStatusOut.model_validate(projection)


@router.post(
    "/disconnect", status_code=status.HTTP_204_NO_CONTENT
)
async def disconnect_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> Response:
    """Null the bearer token + flip the parent row to `disconnected`.
    404 if the org has never connected WhatsApp. Sidecar row (phone_id
    / waba_id) is retained so a future reconnect can pre-fill."""
    row = await disconnect_account(db, actor_id=user.legacy_uuid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No WhatsApp integration found for this org.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=WhatsAppStatusOut)
async def test_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> WhatsAppStatusOut:
    """Ping Meta with stored credentials. Updates `status` / `last_error`
    based on the response. 400 if Meta rejects or if WA isn't connected
    on this org."""
    try:
        projection = await test_connection(db)
    except MetaValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return WhatsAppStatusOut.model_validate(projection)


@router.get("/status", response_model=WhatsAppStatusOut)
async def status_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> WhatsAppStatusOut:
    """Projection used by the Settings UI to render the WA card. Always
    returns 200 — `status='disconnected'` is the natural never-connected
    response, no 404 needed."""
    projection = await get_status(db)
    return WhatsAppStatusOut.model_validate(projection)
