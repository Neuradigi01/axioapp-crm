"""HTTP routes for the WhatsApp Business Account connect surface.

  POST /api/v1/integrations/whatsapp/connect                    → validate + store
  POST /api/v1/integrations/whatsapp/disconnect                 → null token + status
  POST /api/v1/integrations/whatsapp/test                       → ping Meta now
  GET  /api/v1/integrations/whatsapp/status                     → projection (no creds)
  POST /api/v1/integrations/whatsapp/embedded-signup/exchange   → ES popup callback
  POST /api/v1/integrations/whatsapp/templates/sync             → pull Meta library
  GET  /api/v1/integrations/whatsapp/templates                  → list for picker
  GET  /api/v1/integrations/whatsapp/capacity                   → tier + remaining

Admin endpoints (connect/disconnect/test/sync/embedded-signup) gate on
`settings.integrations.manage` — Owner-only by default. The templates
LIST and capacity endpoints gate on `campaigns.read` instead — any
campaign-author needs the picker + quota banner, not just integration
admins. Encrypted credential columns NEVER appear in any response body.

The manual `/connect` endpoint is kept as the "Advanced (self-host)"
fallback for operators who want to bring their own Meta App; the
embedded-signup path is the default Intercom-style flow.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.shared.rate_limit import InMemoryRateLimiter
from src.app.core.integrations.whatsapp.connect import (
    MetaValidationError,
    connect_account,
    disconnect_account,
    get_status,
    test_connection,
)
from src.app.core.integrations.whatsapp.embedded_signup import (
    EmbeddedSignupNotConfigured,
    complete_embedded_signup,
)
from src.app.core.integrations.whatsapp.meta_graph_client import (
    MetaGraphError,
)
from src.app.core.integrations.whatsapp.schemas import (
    EmbeddedSignupExchangeIn,
    EmbeddedSignupExchangeOut,
    WhatsAppCapacityOut,
    WhatsAppConnectIn,
    WhatsAppStatusOut,
    WhatsAppTemplateRead,
    WhatsAppTemplateSyncOut,
)
from src.app.core.integrations.whatsapp.status import get_send_capacity
from src.app.core.integrations.whatsapp.templates import (
    list_templates,
    sync_templates,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(
    prefix="/whatsapp", tags=["Integrations · WhatsApp"]
)


# Per-org rate cap on Embedded Signup exchange attempts — 5 per minute.
# Prevents code-replay loops if the popup flaps. Per-org keying (not
# per-IP) so two operators in the same org sharing the network bench
# don't lock each other out.
_es_exchange_limiter = InMemoryRateLimiter(max_hits=5, window_seconds=60.0)


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


@router.post(
    "/embedded-signup/exchange",
    response_model=EmbeddedSignupExchangeOut,
)
async def embedded_signup_exchange_endpoint(
    payload: EmbeddedSignupExchangeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> EmbeddedSignupExchangeOut:
    """Receive the popup's `(code, phone_number_id, waba_id)` payload,
    run the Embedded Signup orchestration, and return the connected
    projection. Error mapping is pre-bound inside `MetaGraphError`
    (400 for expired code, 403 for permission, 503 for unverified
    webhook, 502 otherwise)."""
    rl = _es_exchange_limiter.check(str(user.org_id))
    if not rl.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many connect attempts — wait "
                f"{int(rl.retry_after)}s and retry."
            ),
            headers={"Retry-After": str(int(rl.retry_after) + 1)},
        )
    try:
        result = await complete_embedded_signup(
            db,
            org_id=user.org_id,
            actor_id=user.legacy_uuid,
            code=payload.code,
            phone_number_id=payload.phone_number_id,
            waba_id=payload.waba_id,
        )
    except EmbeddedSignupNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except MetaGraphError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=exc.user_message,
        )
    return EmbeddedSignupExchangeOut.model_validate(result)


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


# --- Templates (Step 3.5.4) ---------------------------------------------


@router.post(
    "/templates/sync",
    response_model=WhatsAppTemplateSyncOut,
)
async def sync_templates_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> WhatsAppTemplateSyncOut:
    """Pull `/{waba_id}/message_templates` from Meta and reconcile the
    local cache. Returns counts the Settings UI shows in a toast.
    409 if the org is not connected — operator must connect first."""
    try:
        counts = await sync_templates(db)
    except WhatsAppNotConnected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return WhatsAppTemplateSyncOut.model_validate(counts)


@router.get(
    "/templates",
    response_model=list[WhatsAppTemplateRead],
)
async def list_templates_endpoint(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    category: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> list[WhatsAppTemplateRead]:
    """Templates for the active org, optionally filtered by status /
    category. Powers the campaign create-modal picker (Step 3.5.5)."""
    rows = await list_templates(
        db, status=status_filter, category=category
    )
    return [WhatsAppTemplateRead.model_validate(r) for r in rows]


# --- Capacity (Step 3.5.16) ----------------------------------------------


@router.get("/capacity", response_model=WhatsAppCapacityOut)
async def capacity_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("campaigns.read")),
) -> WhatsAppCapacityOut:
    """Current Meta messaging tier + today's used quota for the active
    org. Drives the "X / Y messages remaining today" banner the
    campaign create modal renders before send (Step 3.5.16).

    Gated on `campaigns.read` (same as templates LIST) so any campaign-
    author can see the banner, not just integration admins.

    409 when WhatsApp is not connected — the modal handles that branch
    by hiding the banner entirely and falling back to the existing
    "connect WhatsApp first" empty state."""
    try:
        capacity = await get_send_capacity(db)
    except WhatsAppNotConnected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return WhatsAppCapacityOut.model_validate(capacity)
