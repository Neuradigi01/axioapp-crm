"""Pure CRUD helpers for the ``tbl_channel_endpoints`` + ``tbl_email_endpoint_details`` tables.

Belongs to the Router → Service → DAL contract: no transactions, no
business logic, no imports from :mod:`service` or :mod:`router`. Every
tenant-scoped query filters explicitly on ``org_id`` on top of the
shared tenant listener + RLS policy.

Token-lookup helpers (``find_by_reply_token``, ``find_by_forwarding_token``)
are deliberately NOT ``org_id``-scoped: the caller (the Mailgun webhook
Celery task) starts with only the token and has to resolve the org
from it. The uniqueness constraint on the token columns means at most
one endpoint anywhere in the DB can match — cross-org contamination is
impossible even without an org filter.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ChannelEndpoint,
    EmailEndpointDetails,
)

# Token length matches the shipped mailgun-inbound ``inbound_token``
# generator so backfilled rows and freshly-created rows are
# indistinguishable in shape. 12 chars of URL-safe base64 =
# ~60 bits of entropy post-slice.
_TOKEN_LEN = 12
_TOKEN_COLLISION_MAX_RETRIES = 10


def _generate_token() -> str:
    """12-char URL-safe token. Base64url. ~60 bits of entropy post-slice."""
    return secrets.token_urlsafe(9)[:_TOKEN_LEN]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def find_by_reply_token(
    session: AsyncSession,
    *,
    token: str,
) -> tuple[ChannelEndpoint, EmailEndpointDetails] | None:
    """Reverse-lookup an active endpoint + details by ``reply_token``.

    Not ``org_id``-scoped: token uniqueness guarantees at most one
    match anywhere in the DB. Returns ``None`` if the token is
    unknown or the parent endpoint is inactive.
    """
    result = await session.execute(
        select(ChannelEndpoint, EmailEndpointDetails)
        .join(
            EmailEndpointDetails,
            EmailEndpointDetails.endpoint_id == ChannelEndpoint.id,
        )
        .where(
            EmailEndpointDetails.reply_token == token,
            ChannelEndpoint.is_active.is_(True),
        )
    )
    row = result.first()
    return (row[0], row[1]) if row is not None else None


async def find_by_forwarding_token(
    session: AsyncSession,
    *,
    token: str,
) -> tuple[ChannelEndpoint, EmailEndpointDetails] | None:
    """Reverse-lookup by ``forwarding_token`` (Track 3's f-<token> flow).

    Same semantics as :func:`find_by_reply_token` — token uniqueness
    obviates ``org_id``-scoping.
    """
    result = await session.execute(
        select(ChannelEndpoint, EmailEndpointDetails)
        .join(
            EmailEndpointDetails,
            EmailEndpointDetails.endpoint_id == ChannelEndpoint.id,
        )
        .where(
            EmailEndpointDetails.forwarding_token == token,
            ChannelEndpoint.is_active.is_(True),
        )
    )
    row = result.first()
    return (row[0], row[1]) if row is not None else None


async def find_active_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_type: str | None = None,
) -> list[tuple[ChannelEndpoint, EmailEndpointDetails | None]]:
    """List active endpoints for an org, optionally narrowed by type.

    Returns tuples so callers get details in the same round trip. The
    details row may be ``None`` for endpoints created without a details
    row yet (shouldn't happen after Step 1 backfill, but the join
    tolerates it defensively via ``outerjoin``).
    """
    stmt = (
        select(ChannelEndpoint, EmailEndpointDetails)
        .outerjoin(
            EmailEndpointDetails,
            EmailEndpointDetails.endpoint_id == ChannelEndpoint.id,
        )
        .where(
            ChannelEndpoint.org_id == org_id,
            ChannelEndpoint.is_active.is_(True),
        )
        .order_by(ChannelEndpoint.created_at.desc())
    )
    if endpoint_type is not None:
        stmt = stmt.where(ChannelEndpoint.endpoint_type == endpoint_type)

    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def get_by_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID,
) -> tuple[ChannelEndpoint, EmailEndpointDetails | None] | None:
    """Tenant-scoped point read. Returns None on miss / cross-tenant."""
    result = await session.execute(
        select(ChannelEndpoint, EmailEndpointDetails)
        .outerjoin(
            EmailEndpointDetails,
            EmailEndpointDetails.endpoint_id == ChannelEndpoint.id,
        )
        .where(
            ChannelEndpoint.id == endpoint_id,
            ChannelEndpoint.org_id == org_id,
        )
    )
    row = result.first()
    return (row[0], row[1]) if row is not None else None


async def list_orphan_endpoints(
    session: AsyncSession,
    *,
    cutoff_dt: datetime,
) -> list[ChannelEndpoint]:
    """Endpoints with no details row + created before cutoff.

    Consumed by the Step 5 orphan-endpoint sweeper. Not org-scoped by
    caller — sweeper is a system-actor beat.
    """
    result = await session.execute(
        select(ChannelEndpoint)
        .outerjoin(
            EmailEndpointDetails,
            EmailEndpointDetails.endpoint_id == ChannelEndpoint.id,
        )
        .where(
            EmailEndpointDetails.endpoint_id.is_(None),
            ChannelEndpoint.created_at < cutoff_dt,
            ChannelEndpoint.is_active.is_(True),
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Writes — staged only. commit/refresh belongs to service.
# ---------------------------------------------------------------------------


def add_endpoint(session: AsyncSession, row: ChannelEndpoint) -> ChannelEndpoint:
    """Stage an endpoint INSERT — commit belongs to the caller."""
    session.add(row)
    return row


def add_details(session: AsyncSession, row: EmailEndpointDetails) -> EmailEndpointDetails:
    """Stage a details INSERT — commit belongs to the caller."""
    session.add(row)
    return row


async def create_smtp_reply_capture(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    smtp_sender_id: uuid.UUID,
    label: str,
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    """Stage a new ``smtp_reply_capture`` endpoint + its details row.

    Generates a fresh ``reply_token``; on UNIQUE collision, regenerates
    up to :data:`_TOKEN_COLLISION_MAX_RETRIES` times. Every attempt
    stages a new pair — the caller wraps the whole call in a
    ``session.flush()`` per try so the constraint check runs before
    the next generation.

    Caller commits.
    """
    for _ in range(_TOKEN_COLLISION_MAX_RETRIES):
        token = _generate_token()
        endpoint = ChannelEndpoint(
            org_id=org_id,
            channel=CHANNEL_EMAIL,
            endpoint_type="smtp_reply_capture",
            label=label,
        )
        add_endpoint(session, endpoint)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue

        details = EmailEndpointDetails(
            endpoint_id=endpoint.id,
            org_id=org_id,
            reply_token=token,
            smtp_sender_id=smtp_sender_id,
        )
        add_details(session, details)
        try:
            await session.flush()
            return endpoint, details
        except IntegrityError:
            await session.rollback()
            continue

    raise RuntimeError(
        "channel_endpoints.create_smtp_reply_capture: token collision retry "
        f"limit exceeded ({_TOKEN_COLLISION_MAX_RETRIES})"
    )


async def create_forwarded_address(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    label: str,
    auto_create_contact: bool = True,
    default_assignee_user_id: uuid.UUID | None = None,
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    """Stage a new ``forwarded_address`` endpoint + its details row.

    Generates a fresh ``forwarding_token``; on UNIQUE collision,
    regenerates up to :data:`_TOKEN_COLLISION_MAX_RETRIES` times. Same
    shape as :func:`create_smtp_reply_capture` — the two callers stage
    matching pairs so the sweeper never sees a details-less orphan
    beyond the flush-race window.

    ``auto_create_contact`` and ``default_assignee_user_id`` are
    forwarded-address-specific config (Track 3 Step 3 reads them on
    the ingest path). Both are safe defaults so a caller that doesn't
    pass them lands on the industry-baseline "auto-create contact,
    round-robin assignee".

    Caller commits.
    """
    for _ in range(_TOKEN_COLLISION_MAX_RETRIES):
        token = _generate_token()
        endpoint = ChannelEndpoint(
            org_id=org_id,
            channel=CHANNEL_EMAIL,
            endpoint_type="forwarded_address",
            label=label,
        )
        add_endpoint(session, endpoint)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue

        details = EmailEndpointDetails(
            endpoint_id=endpoint.id,
            org_id=org_id,
            forwarding_token=token,
            auto_create_contact=auto_create_contact,
            default_assignee_user_id=default_assignee_user_id,
        )
        add_details(session, details)
        try:
            await session.flush()
            return endpoint, details
        except IntegrityError:
            await session.rollback()
            continue

    raise RuntimeError(
        "channel_endpoints.create_forwarded_address: token collision retry "
        f"limit exceeded ({_TOKEN_COLLISION_MAX_RETRIES})"
    )


async def create_oauth_mailbox(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    oauth_account_id: uuid.UUID,
    label: str,
) -> tuple[ChannelEndpoint, EmailEndpointDetails]:
    """Stage a new ``oauth_mailbox`` endpoint + its details row.

    No token is generated — OAuth mailboxes receive replies natively
    via provider sync, not via our inbound domain. Caller commits.
    """
    endpoint = ChannelEndpoint(
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type="oauth_mailbox",
        label=label,
    )
    add_endpoint(session, endpoint)
    await session.flush()

    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org_id,
        oauth_account_id=oauth_account_id,
    )
    add_details(session, details)
    await session.flush()
    return endpoint, details


async def deactivate(
    session: AsyncSession,
    *,
    endpoint: ChannelEndpoint,
    reason: str | None = None,
) -> None:
    """Mark endpoint inactive. Row-level state change only — caller commits."""
    endpoint.is_active = False
    endpoint.deactivated_at = datetime.now(UTC)
    if reason is not None:
        endpoint.deactivation_reason = reason


async def soft_delete_orphans_older_than(
    session: AsyncSession,
    *,
    cutoff_dt: datetime,
    reason: str = "orphan_sweeper",
) -> int:
    """Mark all orphan endpoints inactive. Returns count.

    Consumed by the Step 5 sweeper. Caller commits.
    """
    orphans = await list_orphan_endpoints(session, cutoff_dt=cutoff_dt)
    now = datetime.now(UTC)
    for e in orphans:
        e.is_active = False
        e.deactivated_at = now
        e.deactivation_reason = reason
    return len(orphans)


async def list_oauth_endpoints_backed_by_disconnected_accounts(
    session: AsyncSession,
    *,
    disconnected_since: datetime,
) -> list[ChannelEndpoint]:
    """OAuth-mailbox endpoints whose backing ``tbl_email_accounts`` row
    has been ``disconnected_at <= disconnected_since`` for the whole
    grace window.

    Consumed by the Step 5 sweeper. Cross-tenant (system-actor beat).
    Uses raw SQL so the ORM tenant filter doesn't scope the read to
    ``NULL org`` and drop every row.
    """
    from sqlalchemy import text

    result = await session.execute(
        text(
            """
            SELECT e.id
              FROM tbl_channel_endpoints e
              JOIN tbl_email_endpoint_details d ON d.endpoint_id = e.id
              JOIN tbl_email_accounts a ON a.id = d.oauth_account_id
             WHERE e.is_active = true
               AND e.endpoint_type = 'oauth_mailbox'
               AND a.sync_state = 'disconnected'
               AND a.disconnected_at IS NOT NULL
               AND a.disconnected_at <= :cutoff
            """
        ),
        {"cutoff": disconnected_since},
    )
    ids = [row[0] for row in result.all()]
    if not ids:
        return []
    rows = await session.execute(select(ChannelEndpoint).where(ChannelEndpoint.id.in_(ids)))
    return list(rows.scalars().all())


__all__ = [
    "find_by_reply_token",
    "find_by_forwarding_token",
    "find_active_for_org",
    "get_by_id",
    "list_orphan_endpoints",
    "list_oauth_endpoints_backed_by_disconnected_accounts",
    "add_endpoint",
    "add_details",
    "create_forwarded_address",
    "create_smtp_reply_capture",
    "create_oauth_mailbox",
    "deactivate",
    "soft_delete_orphans_older_than",
]
