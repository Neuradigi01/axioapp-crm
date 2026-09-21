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
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit import service as audit
from src.app.core.channel_endpoints import data_access
from src.app.core.channel_endpoints.schemas import (
    ChannelEndpointOut,
    EmailEndpointDetailsOut,
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
    rows = await data_access.find_active_for_org(
        db, org_id=org_id, endpoint_type=endpoint_type
    )
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
    "list_endpoints_for_org",
    "deactivate_endpoint",
]
