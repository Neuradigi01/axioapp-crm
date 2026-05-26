"""HTTP routes for ad-integration management.

  GET    /api/v1/integrations              → list rows for the org
  DELETE /api/v1/integrations/{provider}   → disconnect a provider

Both gated by `settings.integrations.manage` (registered in
`core/integrations/module.py` and auto-picked-up by the lifespan
permission-registration step in `main.py`).

OAuth callback + connect endpoints land in Step 2 (Google) and
Step 4 (Meta) — this step only ships the management surface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.models import IntegrationProvider
from src.app.core.integrations.schemas import (
    IntegrationProviderLiteral,
    IntegrationRead,
)
from src.app.core.integrations.service import (
    disconnect as disconnect_integration,
    list_all,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/integrations", tags=["Ad Integrations"])


@router.get("", response_model=list[IntegrationRead])
async def list_integrations_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> list[IntegrationRead]:
    """Return every integration row for the active tenant. The response
    NEVER includes the encrypted-token columns — `IntegrationRead`
    doesn't declare them."""
    rows = await list_all(db)
    return [IntegrationRead.model_validate(r) for r in rows]


@router.delete(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT
)
async def disconnect_integration_endpoint(
    provider: IntegrationProviderLiteral,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.manage")
    ),
) -> Response:
    """Disconnect a provider — clears tokens + flips status to
    `disconnected`. Idempotent — re-disconnecting returns 204 without
    a second audit event. 404 if the org has never connected this
    provider."""
    provider_enum = IntegrationProvider(provider)
    row = await disconnect_integration(
        db, provider=provider_enum, actor_id=user.legacy_uuid
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider} integration found for this org.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
