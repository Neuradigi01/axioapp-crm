"""HTTP endpoints for the ``/api/v1/channel-endpoints`` surface.

Gated by ``email.accounts.manage`` — the same permission key the
existing email-senders and email-accounts routers use. Channel
endpoints are the same admin surface (managing your org's inbound
identities), so grouping them under one permission key keeps role
templates simple. See ``core.email_senders.module`` for the same
reuse rationale.

Step 2 ships only the admin-overview surface: list + deactivate.
Endpoint-creation flows for the concrete types land alongside their
respective tracks (Track 3 wires ``forwarded_address`` create,
Track 2 wires ``oauth_mailbox`` visibility, etc.).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.channel_endpoints import service
from src.app.core.channel_endpoints.schemas import (
    ChannelEndpointListOut,
    DeactivateEndpointIn,
    EndpointType,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/channel-endpoints", tags=["Channel Endpoints"])


@router.get("", response_model=ChannelEndpointListOut)
async def list_endpoints_endpoint(
    endpoint_type: EndpointType | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> ChannelEndpointListOut:
    """List the org's active channel endpoints.

    Optional ``endpoint_type`` narrows to one flavour (e.g. only
    ``forwarded_address`` for the Inbound Addresses tab). Details
    row is included per endpoint.
    """
    items = await service.list_endpoints_for_org(
        db, org_id=user.org_id, endpoint_type=endpoint_type
    )
    return ChannelEndpointListOut(items=items)


@router.post(
    "/{endpoint_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_endpoint_endpoint(
    endpoint_id: uuid.UUID,
    payload: DeactivateEndpointIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Soft-delete an endpoint.

    Idempotent — deactivating an already-inactive endpoint returns
    204 with no side-effects. Cross-org / unknown ID returns 404
    (no info leak about whether the ID exists in another org).
    """
    await service.deactivate_endpoint(
        db,
        org_id=user.org_id,
        endpoint_id=endpoint_id,
        actor_user_id=user.id,
        reason=payload.reason if payload else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
