"""HTTP routes for ad-integration management.

  GET    /api/v1/integrations                            → list rows for the org
  DELETE /api/v1/integrations/{provider}                 → disconnect a provider
  POST   /api/v1/integrations/{provider}/webhook/rotate  → mint new webhook secret
  GET    /api/v1/integrations/subscriptions              → list form subscriptions
  POST   /api/v1/integrations/subscriptions              → create
  PATCH  /api/v1/integrations/subscriptions/{id}         → update mapping / enable
  DELETE /api/v1/integrations/subscriptions/{id}         → remove
  GET    /api/v1/integrations/dlq                        → list dead-letter rows
  POST   /api/v1/integrations/dlq/{id}/replay            → re-enqueue

All admin endpoints are gated by `settings.integrations.manage`.

OAuth callback (Step 2) + the public webhook receiver (Step 3) are
provider-specific and live on the google subrouter — those are the
ONLY routes in this surface that don't gate on a CRM JWT (the OAuth
state and the webhook secret are the trust roots respectively).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.google.dlq import replay_dlq
from src.app.core.integrations.google.router import router as google_router
from src.app.core.integrations.google.webhook import (
    router as google_webhook_router,
)
from src.app.core.integrations.google_calendar.router import (
    router as google_calendar_router,
)
from src.app.core.integrations.meta.router import router as meta_router
from src.app.core.integrations.meta.webhook import (
    router as meta_webhook_router,
)
from src.app.core.integrations.whatsapp_web.router import (
    router as whatsapp_web_router,
)
from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.schemas import (
    IntegrationDLQListResponse,
    IntegrationDLQRead,
    IntegrationProviderLiteral,
    IntegrationRead,
    IntegrationStatusResponse,
    IntegrationSubscriptionCreate,
    IntegrationSubscriptionRead,
    IntegrationSubscriptionUpdate,
    SubscriptionMappingUpdate,
)
from src.app.core.integrations.service import (
    create_subscription,
    delete_subscription,
    discard_dlq,
    list_all,
    list_dlq,
    list_subscriptions,
    rotate_webhook_secret,
    update_subscription,
    update_subscription_mapping,
)
from src.app.core.integrations.service import (
    disconnect as disconnect_integration,
)
from src.app.core.integrations.status import build_status
from src.app.core.integrations.whatsapp.router import (
    router as whatsapp_router,
)
from src.app.core.leads.imports.targets import list_target_keys
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/integrations", tags=["Ad Integrations"])

# Provider-specific subrouters mount UNDER /integrations/ via include
# at module-import time — keeps the registration in one place and
# means main.py only needs the one parent include. Google subrouter
# uses its own /integrations/google prefix (full path becomes
# /api/v1/integrations/google/...) — declared on the subrouter itself,
# so include is one line, no double-prefix.
router.include_router(google_router)
# Public webhook receiver — same /google prefix, separate router so the
# public endpoint doesn't accidentally inherit any admin-only deps
# someone might attach to the OAuth subrouter later.
router.include_router(google_webhook_router)
# tasks/google-calendar-sync Step 2 — per-user Google Calendar OAuth.
# Full paths become /api/v1/integrations/google-calendar/*. Distinct
# module from google_router (per-org Ads OAuth) because Calendar sync
# is fundamentally per-user (each employee connects their own account).
router.include_router(google_calendar_router)
# Meta subrouter — symmetric to Google. Full paths become
# /api/v1/integrations/meta/...
router.include_router(meta_router)
# Meta webhook receiver — single fixed URL per environment (Meta's
# webhook model). Separate router so the public endpoint doesn't
# inherit any admin-only deps that might land on the OAuth router.
router.include_router(meta_webhook_router)
# WhatsApp subrouter — Step 3.5.1. Connect/disconnect/test/status for
# the WhatsApp Business Cloud API channel. Full paths become
# /api/v1/integrations/whatsapp/...
router.include_router(whatsapp_router)
# WhatsApp Web (unofficial / Baileys) subrouter — Step 4 of the
# whatsapp-unofficial track. Mount is in place now; the first
# endpoint (POST /connect) lands in Step 5. Full paths become
# /api/v1/integrations/whatsapp-web/...
router.include_router(whatsapp_web_router)


@router.get("", response_model=list[IntegrationRead])
async def list_integrations_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> list[IntegrationRead]:
    """Return every integration row for the active tenant. The response
    NEVER includes the encrypted-token columns — `IntegrationRead`
    doesn't declare them."""
    rows = await list_all(db)
    return [IntegrationRead.model_validate(r) for r in rows]


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_integration_endpoint(
    provider: IntegrationProviderLiteral,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> Response:
    """Disconnect a provider — clears tokens + flips status to
    `disconnected`. Idempotent — re-disconnecting returns 204 without
    a second audit event. 404 if the org has never connected this
    provider."""
    provider_enum = IntegrationProvider(provider)
    row = await disconnect_integration(db, provider=provider_enum, actor_id=user.legacy_uuid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider} integration found for this org.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Webhook secret rotation --------------------------------------------


@router.post(
    "/{provider}/webhook/rotate",
    response_model=IntegrationRead,
)
async def rotate_webhook_endpoint(
    provider: IntegrationProviderLiteral,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationRead:
    """Mint a fresh webhook secret. Old URL stops authenticating
    immediately — Settings UI must show the new URL to the Owner and
    instruct them to update it in the ad platform's webhook config.
    404 if the org has not connected this provider."""
    provider_enum = IntegrationProvider(provider)
    row = await rotate_webhook_secret(db, provider=provider_enum)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider} integration found for this org.",
        )
    return IntegrationRead.model_validate(row)


# --- Subscriptions CRUD --------------------------------------------------


@router.get(
    "/subscriptions",
    response_model=list[IntegrationSubscriptionRead],
)
async def list_subscriptions_endpoint(
    integration_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> list[IntegrationSubscriptionRead]:
    """List form subscriptions in this org, optionally filtered to one
    integration. The Settings UI loads this when rendering each
    provider's picker."""
    rows = await list_subscriptions(db, integration_id=integration_id)
    return [IntegrationSubscriptionRead.model_validate(r) for r in rows]


@router.post(
    "/subscriptions",
    response_model=IntegrationSubscriptionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription_endpoint(
    payload: IntegrationSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationSubscriptionRead:
    """Subscribe to a Google/Meta form. Body specifies the integration
    + the platform's form_id + initial field mapping. 409 if the
    integration is already subscribed to that form."""
    row = await create_subscription(db, org_id=user.org_id, payload=payload)
    return IntegrationSubscriptionRead.model_validate(row)


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=IntegrationSubscriptionRead,
)
async def update_subscription_endpoint(
    subscription_id: uuid.UUID,
    payload: IntegrationSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationSubscriptionRead:
    """Partial update — typically the field-mapping editor in Step 8
    or the enable/disable toggle on the Settings card. Returns the
    updated row."""
    row = await update_subscription(db, subscription_id=subscription_id, payload=payload)
    return IntegrationSubscriptionRead.model_validate(row)


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_subscription_endpoint(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> Response:
    """Hard-delete a subscription. Future deliveries for the removed
    form will DLQ. 404 if no such row in this org."""
    removed = await delete_subscription(db, subscription_id=subscription_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Step 8: Subscription field-mapping editor --------------------------


@router.put(
    "/subscriptions/{subscription_id}/mapping",
    response_model=IntegrationSubscriptionRead,
)
async def update_subscription_mapping_endpoint(
    subscription_id: uuid.UUID,
    payload: SubscriptionMappingUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationSubscriptionRead:
    """Replace the subscription's `field_mapping`. Step-8 mapping
    editor calls this on Save. Targets are validated against the
    bulk-import target registry (`leads.imports.targets`) — sending
    an unknown CRM target key returns 422 so the editor can surface
    a precise validation error per row.

    Empty mapping is allowed (means "drop everything" — the worker
    will DLQ inbound payloads until at least one field is mapped
    again). Sending the same mapping again is idempotent."""
    if payload.mapping:
        valid_keys = await list_target_keys(db)
        invalid = sorted(k for k in payload.mapping.values() if k not in valid_keys)
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Unknown CRM target keys: "
                    f"{invalid}. Hit GET /api/v1/leads/import/targets "
                    "for the valid list."
                ),
            )
    row = await update_subscription_mapping(
        db,
        subscription_id=subscription_id,
        mapping=payload.mapping,
    )
    return IntegrationSubscriptionRead.model_validate(row)


# --- DLQ list + replay + discard (Step 8 extends Step 3) ----------------


@router.get(
    "/dlq",
    response_model=IntegrationDLQListResponse,
)
async def list_dlq_endpoint(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    provider: IntegrationProviderLiteral | None = Query(default=None),
    include_replayed: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationDLQListResponse:
    """Paginated DLQ for the active tenant.

    `provider` filters to one platform. `include_replayed=false`
    drops rows that have been replayed OR discarded — drives the
    Step-8 status panel's "open failures" view. Step 7's summary
    card uses the default (everything) since it just needs a total."""
    provider_enum = IntegrationProvider(provider) if provider else None
    rows, total = await list_dlq(
        db,
        page=page,
        size=size,
        provider=provider_enum,
        include_replayed=include_replayed,
    )
    return IntegrationDLQListResponse(
        items=[IntegrationDLQRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "/dlq/{dlq_id}/discard",
    response_model=IntegrationDLQRead,
)
async def discard_dlq_endpoint(
    dlq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationDLQRead:
    """Soft-discard a DLQ row — stamps `replayed_at = now()` with
    `replayed_by = NULL`. The NULL `replayed_by` is the discriminator:
    a real replay always carries the actor; a discard never does.
    Row survives for forensic trail; the status panel + open-failures
    list exclude it. 404 if the row doesn't exist."""
    row = await discard_dlq(db, dlq_id=dlq_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DLQ row not found",
        )
    return IntegrationDLQRead.model_validate(row)


@router.get(
    "/status",
    response_model=IntegrationStatusResponse,
)
async def integration_status_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationStatusResponse:
    """Per-provider delivery snapshot for the Settings dashboard.
    Polled every ~30s by the SPA. Always returns ALL providers
    (even un-connected) so the panel renders consistent tiles.

    Counts come from `audit_logs` events (Step 3 / Step 5 workers
    emit `integration.webhook.received` on success +
    `integration.webhook.dlq` on failure)."""
    return await build_status(db)


@router.post(
    "/dlq/{dlq_id}/replay",
    response_model=IntegrationDLQRead,
)
async def replay_dlq_endpoint(
    dlq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.manage")),
) -> IntegrationDLQRead:
    """Re-enqueue a DLQ payload through the matching provider's
    Celery task. Marks the row as replayed (the row survives so an
    operator can see what's been retried). 404 if missing, 409 if the
    original integration has been hard-deleted."""
    row = await replay_dlq(db, dlq_id=dlq_id, actor_id=user.legacy_uuid)
    return IntegrationDLQRead.model_validate(row)
