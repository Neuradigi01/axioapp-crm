"""Business logic for the channel-endpoints module.

Two entry points in Step 2:

  * :func:`list_endpoints_for_org` — org-scoped read with optional
    endpoint-type filter. Returns the ORM tuples wrapped in
    response schemas; router flattens to the API surface.

  * :func:`deactivate_endpoint` — soft-delete. Row-locked so two
    admins hitting the button concurrently serialise cleanly (the
    second one sees the deactivated row and no-ops); audit event
    fires with ``actor_user_id`` for compliance.

Only this file holds transactions. The DAL never
commits/flushes/refreshes; the router only calls this service.

Concrete endpoint-creation flows for the various types
(:data:`smtp_reply_capture`, :data:`oauth_mailbox`,
:data:`forwarded_address`, ...) will land alongside each concrete
track (Track 3 wires ``forwarded_address``, etc.). Step 2 ships the
plumbing without any new user-facing creation path.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit import service as audit
from src.app.core.channel_endpoints import data_access
from src.app.core.channel_endpoints.models import ChannelEndpoint, EmailEndpointDetails
from src.app.core.channel_endpoints.schemas import (
    AssigneeRef,
    ChannelEndpointOut,
    EmailEndpointDetailsOut,
    ForwardedAddressOut,
    TestInboundStatusOut,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def list_endpoints_for_org(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_type: str | None = None,
) -> list[ChannelEndpointOut]:
    """List active endpoints for an org.

    Owner/Admin surface — router enforces permission. Includes each
    endpoint's details block in the same response so callers don't
    chase a second endpoint.
    """
    rows = await data_access.find_active_for_org(db, org_id=org_id, endpoint_type=endpoint_type)
    return [_to_out(endpoint, details) for endpoint, details in rows]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def deactivate_endpoint(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str | None = None,
) -> None:
    """Soft-delete an endpoint.

    Raises 404 on cross-org / unknown ID. Idempotent — deactivating
    an already-inactive row returns 204 without side-effects (no
    audit spam). Row-lock via SELECT-then-mutate in a single
    transaction serialises concurrent hits at the DB level.
    """
    pair = await data_access.get_by_id(db, org_id=org_id, endpoint_id=endpoint_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )

    endpoint, _details = pair
    if not endpoint.is_active:
        # Idempotent: already deactivated → no-op, no audit spam.
        return

    await data_access.deactivate(db, endpoint=endpoint, reason=reason or "manual")
    await db.commit()
    await db.refresh(endpoint)

    await audit.log(
        "channel_endpoint.deactivated",
        entity_type="channel_endpoint",
        entity_id=endpoint.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "endpoint_type": endpoint.endpoint_type,
            "label": endpoint.label,
            "reason": reason or "manual",
        },
    )


# ---------------------------------------------------------------------------
# tasks/email-inbound-forwarding Step 2 — forwarded-address creation.
# ---------------------------------------------------------------------------


async def list_forwarded_addresses_for_org(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[ForwardedAddressOut]:
    """List every active ``forwarded_address`` endpoint the org has,
    composed into the response shape.

    Different from :func:`list_endpoints_for_org` in one important
    way: this ships the raw ``forwarding_token`` composed into the
    ``forwarding_address`` string, matching what the create response
    returns. The generic listing endpoint deliberately omits the
    token because :class:`EmailEndpointDetailsOut` doesn't model it;
    surfacing the composed address here (in a purpose-built response)
    lets the inbox-settings UI display the copy-paste address without
    needing to store the create-response client-side.
    """
    rows = await data_access.find_active_for_org(
        db, org_id=org_id, endpoint_type="forwarded_address"
    )
    out: list[ForwardedAddressOut] = []
    for endpoint, details in rows:
        if details is None:
            continue
        assignee_ref = await _resolve_assignee_ref(
            db, assignee_uuid=details.default_assignee_user_id
        )
        out.append(_to_forwarded_address_out(endpoint, details, assignee_ref))
    return out


async def create_forwarded_address_endpoint(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    label: str,
    auto_create_contact: bool = True,
    default_assignee_user_id: uuid.UUID | None = None,
) -> ForwardedAddressOut:
    """Create a fresh ``forwarded_address`` endpoint for the caller's org.

    Owner/Admin only — the router enforces the permission gate; this
    service function trusts the caller has been authorised. Validates
    the optional ``default_assignee_user_id`` belongs to the SAME org
    before touching the DB (cross-org assignee is a hard 400).

    Token generation delegates to :func:`data_access.create_forwarded_address`
    (mirrors the shipped ``create_smtp_reply_capture`` retry loop —
    ~60 bits of entropy, 10 collision retries).

    Returns the response schema with a composed
    ``f-<token>@<INBOUND_EMAIL_DOMAIN>`` address — the raw token stays
    on the DB row + is never surfaced to a client.
    """
    if default_assignee_user_id is not None:
        await _validate_assignee_in_org(db, org_id=org_id, assignee_uuid=default_assignee_user_id)

    endpoint, details = await data_access.create_forwarded_address(
        db,
        org_id=org_id,
        label=label,
        auto_create_contact=auto_create_contact,
        default_assignee_user_id=default_assignee_user_id,
    )
    await db.commit()
    await db.refresh(endpoint)
    await db.refresh(details)

    assignee_ref = await _resolve_assignee_ref(db, assignee_uuid=default_assignee_user_id)

    await audit.log(
        "forwarded_address_endpoint.created",
        entity_type="channel_endpoint",
        entity_id=endpoint.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "endpoint_type": endpoint.endpoint_type,
            "label": endpoint.label,
            "auto_create_contact": auto_create_contact,
            "default_assignee_user_id": (
                str(default_assignee_user_id) if default_assignee_user_id else None
            ),
        },
    )

    return _to_forwarded_address_out(endpoint, details, assignee_ref)


async def update_forwarded_address_endpoint(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    label: str | None = None,
    auto_create_contact: bool | None = None,
    default_assignee_user_id: uuid.UUID | None = None,
    unset_assignee: bool = False,
) -> ForwardedAddressOut:
    """Partial-update a ``forwarded_address`` endpoint's config.

    Every mutable field is optional so the inbox-settings row-inline
    toggles PATCH one attribute at a time. Cross-org / unknown id →
    404; wrong endpoint_type → 404 (surface indistinguishable from
    "not found" so this endpoint can't be used to probe endpoint
    types). Cross-org assignee → 400.

    ``unset_assignee=True`` explicitly clears the assignee back to
    round-robin. This distinguishes "user didn't send the field"
    (leave it alone) from "user chose 'no assignee'" (set to NULL).

    Audit event ``forwarded_address_endpoint.updated`` fires with the
    diff of changed fields.
    """
    pair = await data_access.get_by_id(db, org_id=org_id, endpoint_id=endpoint_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )
    endpoint, details = pair
    if endpoint.endpoint_type != "forwarded_address" or details is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )

    changes: dict[str, Any] = {}
    if label is not None and label != endpoint.label:
        changes["label"] = {"before": endpoint.label, "after": label}
        endpoint.label = label
    if auto_create_contact is not None and (auto_create_contact != details.auto_create_contact):
        changes["auto_create_contact"] = {
            "before": details.auto_create_contact,
            "after": auto_create_contact,
        }
        details.auto_create_contact = auto_create_contact
    if unset_assignee:
        if details.default_assignee_user_id is not None:
            changes["default_assignee_user_id"] = {
                "before": str(details.default_assignee_user_id),
                "after": None,
            }
            details.default_assignee_user_id = None
    elif (
        default_assignee_user_id is not None
        and default_assignee_user_id != details.default_assignee_user_id
    ):
        await _validate_assignee_in_org(db, org_id=org_id, assignee_uuid=default_assignee_user_id)
        changes["default_assignee_user_id"] = {
            "before": (
                str(details.default_assignee_user_id) if details.default_assignee_user_id else None
            ),
            "after": str(default_assignee_user_id),
        }
        details.default_assignee_user_id = default_assignee_user_id

    if changes:
        await db.commit()
        await db.refresh(endpoint)
        await db.refresh(details)
        await audit.log(
            "forwarded_address_endpoint.updated",
            entity_type="channel_endpoint",
            entity_id=endpoint.id,
            org_id=org_id,
            user_id=actor_user_id,
            after=changes,
        )

    assignee_ref = await _resolve_assignee_ref(db, assignee_uuid=details.default_assignee_user_id)
    return _to_forwarded_address_out(endpoint, details, assignee_ref)


async def get_test_inbound_status(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
) -> TestInboundStatusOut:
    """Return the "did a test email arrive yet?" state for a
    ``forwarded_address`` endpoint.

    Consumed by the Step 6 wizard's Step 3 polling loop. Returns
    ``status='received'`` as soon as ``details.last_inbound_at`` is
    non-null (Step 3 ingest stamps it on every successful message).
    Cross-org / unknown id → 404; non-forwarded_address → 404 (same
    info-leak posture as :func:`update_forwarded_address_endpoint`).
    """
    pair = await data_access.get_by_id(db, org_id=org_id, endpoint_id=endpoint_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )
    endpoint, details = pair
    if endpoint.endpoint_type != "forwarded_address" or details is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )
    return TestInboundStatusOut(
        status="received" if details.last_inbound_at is not None else "waiting",
        last_inbound_at=details.last_inbound_at,
    )


async def delete_forwarded_address_endpoint(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    """Hard-delete a ``forwarded_address`` endpoint.

    Removes both the endpoint row and its details row via cascade FK.
    Historical messages persisted with this endpoint's id in their
    ``payload.endpoint_id`` stay intact — they carry the id as a
    string, not an FK, so the deletion doesn't cascade into
    conversations.

    Cross-org / unknown id → 404. Wrong endpoint_type → 404 (same
    info-leak reasoning as ``update_``). Audit
    ``forwarded_address_endpoint.deleted`` fires before the DELETE
    lands so an aborted commit doesn't lose the audit trail.
    """
    pair = await data_access.get_by_id(db, org_id=org_id, endpoint_id=endpoint_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )
    endpoint, details = pair
    if endpoint.endpoint_type != "forwarded_address":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="channel endpoint not found",
        )

    forwarding_token = details.forwarding_token if details else None
    await audit.log(
        "forwarded_address_endpoint.deleted",
        entity_type="channel_endpoint",
        entity_id=endpoint.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "label": endpoint.label,
            # Include the token here so an operator can trace which
            # inbound address was killed. Frontends never see this
            # payload (audit-logs router gates on ``audit.read``).
            "forwarding_token": forwarding_token,
        },
    )
    await data_access.delete_endpoint(db, endpoint=endpoint)
    await db.commit()


async def _validate_assignee_in_org(
    db: AsyncSession, *, org_id: uuid.UUID, assignee_uuid: uuid.UUID
) -> None:
    """Reject a ``default_assignee_user_id`` that doesn't belong to the
    caller's org. Otherwise a cross-org UUID would leak org-membership
    signals via the ingest task's routing.

    Late import: users DAL is a peer module — importing at file top
    would create a service→service import chain the pin-tests grumble
    about (Router → Service → DAL is preferred, but service→service
    is tolerated when it fires a permission / ownership check).
    """
    from src.app.core.users import data_access as users_da

    user = await users_da.get_user_by_uuid(db, assignee_uuid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_assignee_user_id does not identify a known user",
        )
    membership = await users_da.get_membership(
        db, user_member_id=user.id, org_id=org_id, active_only=True
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_assignee_user_id must be a member of this org",
        )


async def _resolve_assignee_ref(
    db: AsyncSession, *, assignee_uuid: uuid.UUID | None
) -> AssigneeRef | None:
    """Fetch the user row (already validated in the caller) and build
    the compact :class:`AssigneeRef` for the response. Returns None
    when no assignee is set — the JSON field is `null`, not omitted."""
    if assignee_uuid is None:
        return None
    from src.app.core.users import data_access as users_da

    user = await users_da.get_user_by_uuid(db, assignee_uuid)
    if user is None:
        # Defensive: shouldn't happen because create_forwarded_address_endpoint
        # validates in the same transaction. Fail-soft to None so a
        # deleted user between validate and refresh doesn't 500 the
        # response.
        return None
    return AssigneeRef(id=assignee_uuid, name=user.full_name or user.email or "")


def _to_forwarded_address_out(
    endpoint: ChannelEndpoint,
    details: EmailEndpointDetails,
    assignee_ref: AssigneeRef | None,
) -> ForwardedAddressOut:
    """Compose the response schema. The raw ``forwarding_token`` is
    combined with ``INBOUND_EMAIL_DOMAIN`` here so the client only ever
    sees the customer-facing address, never the token itself."""
    inbound_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").strip()
    token = details.forwarding_token or ""
    # Fallback to a "TBD" placeholder rather than a broken address
    # if INBOUND_EMAIL_DOMAIN is somehow unset in this deploy — the
    # frontend can render a clear "your platform admin needs to
    # configure the inbound domain" hint instead of an empty string.
    address = (
        f"f-{token}@{inbound_domain}"
        if inbound_domain
        else f"f-{token}@<inbound-domain-not-configured>"
    )
    return ForwardedAddressOut(
        id=endpoint.id,
        label=endpoint.label,
        forwarding_address=address,
        auto_create_contact=details.auto_create_contact,
        default_assignee=assignee_ref,
        is_active=endpoint.is_active,
        last_inbound_at=details.last_inbound_at,
        created_at=endpoint.created_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(endpoint, details) -> ChannelEndpointOut:
    """Build the response schema from an (endpoint, details) ORM pair.

    Kept in the service layer (not the DAL) so the DAL stays pure
    ORM; kept out of the router so the router remains a receptionist.
    """
    out = ChannelEndpointOut.model_validate(endpoint)
    if details is not None:
        out.details = EmailEndpointDetailsOut.model_validate(details)
    return out


__all__ = [
    "create_forwarded_address_endpoint",
    "deactivate_endpoint",
    "delete_forwarded_address_endpoint",
    "get_test_inbound_status",
    "list_endpoints_for_org",
    "list_forwarded_addresses_for_org",
    "update_forwarded_address_endpoint",
]
