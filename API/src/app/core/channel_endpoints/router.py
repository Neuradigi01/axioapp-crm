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
    CreateForwardedAddressIn,
    DeactivateEndpointIn,
    EndpointType,
    ForwardedAddressOut,
    TestInboundStatusOut,
    UpdateForwardedAddressIn,
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


# ---------------------------------------------------------------------------
# tasks/email-inbound-forwarding Step 5 — forwarded-address CRUD.
# ---------------------------------------------------------------------------


@router.get(
    "/forwarded-address",
    response_model=list[ForwardedAddressOut],
)
async def list_forwarded_addresses_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> list[ForwardedAddressOut]:
    """List the org's ``forwarded_address`` endpoints with composed
    ``f-<token>@<INBOUND_EMAIL_DOMAIN>`` addresses.

    Purpose-built for the Inbound Addresses tab — the generic
    ``GET /channel-endpoints`` endpoint deliberately omits the
    ``forwarding_token`` (never in ``EmailEndpointDetailsOut``) so
    the tab needs THIS endpoint to render the copy-paste address
    column without storing the create-response client-side.
    """
    return await service.list_forwarded_addresses_for_org(db, org_id=user.org_id)


@router.post(
    "/forwarded-address",
    response_model=ForwardedAddressOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_forwarded_address_endpoint(
    payload: CreateForwardedAddressIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> ForwardedAddressOut:
    """Claim a fresh ``f-<token>@<INBOUND_EMAIL_DOMAIN>`` address for
    the caller's org.

    Owner/Admin only via the shared ``email.accounts.manage`` gate.
    Cross-org ``default_assignee_user_id`` in the payload → 400.
    """
    return await service.create_forwarded_address_endpoint(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        label=payload.label,
        auto_create_contact=payload.auto_create_contact,
        default_assignee_user_id=payload.default_assignee_user_id,
    )


@router.patch(
    "/forwarded-address/{endpoint_id}",
    response_model=ForwardedAddressOut,
)
async def update_forwarded_address_endpoint(
    endpoint_id: uuid.UUID,
    payload: UpdateForwardedAddressIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> ForwardedAddressOut:
    """Partial-update a forwarded-address endpoint's config.

    Every field in ``UpdateForwardedAddressIn`` is optional; only
    supplied fields land on the row. ``default_assignee_user_id=None``
    with the field present in the payload clears the assignee — the
    inbox-settings row-inline dropdown wires "Unassigned" to this
    branch via the ``unset_assignee`` flag on the service call.
    """
    sent = payload.model_dump(exclude_unset=True)
    return await service.update_forwarded_address_endpoint(
        db,
        org_id=user.org_id,
        endpoint_id=endpoint_id,
        actor_user_id=user.id,
        label=payload.label,
        auto_create_contact=payload.auto_create_contact,
        default_assignee_user_id=payload.default_assignee_user_id,
        unset_assignee=(
            "default_assignee_user_id" in sent and payload.default_assignee_user_id is None
        ),
    )


@router.get(
    "/forwarded-address/{endpoint_id}/test-inbound-status",
    response_model=TestInboundStatusOut,
)
async def test_inbound_status_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> TestInboundStatusOut:
    """Report whether a test email has arrived at this forwarded-
    address endpoint yet.

    Consumed by the Step-6 wizard's Step 3 polling loop (5s cadence,
    5min ceiling). Returns ``status='received'`` as soon as the
    endpoint's ``last_inbound_at`` is populated. Cross-org / unknown
    id / wrong endpoint_type → 404 (info-leak posture matches the
    other forwarded-address endpoints).
    """
    return await service.get_test_inbound_status(
        db,
        org_id=user.org_id,
        endpoint_id=endpoint_id,
    )


@router.delete(
    "/forwarded-address/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_forwarded_address_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    """Hard-delete a forwarded-address endpoint.

    Differs from ``POST /{id}/deactivate`` (soft-delete): the endpoint
    row is removed entirely, its details cascade off via FK, and the
    ``f-<token>@…`` address stops resolving forever. Historical
    messages on any conversation the endpoint touched stay intact —
    their ``payload.endpoint_id`` is a string, not an FK.
    """
    await service.delete_forwarded_address_endpoint(
        db,
        org_id=user.org_id,
        endpoint_id=endpoint_id,
        actor_user_id=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
