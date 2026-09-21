"""Coverage for Step 1 of tasks/email-endpoint-abstraction/.

Verifies the two new tables and their constraints are in place:

  * ``tbl_channel_endpoints`` — parent endpoint model (any channel).
  * ``tbl_email_endpoint_details`` — email-specific 1:1 detail row.

Test-DB behaviour: :func:`conftest.test_db` calls
``Base.metadata.create_all`` per test, so every model column, index,
and constraint above is created fresh. The migration itself
(``0232_channel_endpoints``) is tested indirectly here — its DDL and
the ORM's declared ``__table_args__`` must agree, and if they
diverge the CI schema-drift pin-test catches it.

The **backfill** logic (INSERT ... SELECT from ``tbl_email_smtp_senders``
and ``tbl_email_accounts``) is verified against a live DB after
``run.cmd upgrade`` — not here. See ``SMOKE.md`` in the track folder.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.app.core.channel_endpoints.models import (
    CHANNEL_EMAIL,
    ENDPOINT_TYPE_OAUTH_MAILBOX,
    ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    ChannelEndpoint,
    EmailEndpointDetails,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Endpoints Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"ep-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


def _make_endpoint(
    *,
    org_id: uuid.UUID,
    endpoint_type: str = ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    label: str = "sender@example.com",
) -> ChannelEndpoint:
    return ChannelEndpoint(
        id=uuid.uuid4(),
        org_id=org_id,
        channel=CHANNEL_EMAIL,
        endpoint_type=endpoint_type,
        label=label,
    )


# ---------------------------------------------------------------------------
# Schema — tables and columns present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_tbl_channel_endpoints(test_db):
    """Parent endpoint table exists with the expected columns."""
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_channel_endpoints'
            """
        )
    )
    cols = {row[0] for row in result}
    expected = {
        "id",
        "org_id",
        "channel",
        "endpoint_type",
        "label",
        "is_active",
        "deactivated_at",
        "deactivation_reason",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


@pytest.mark.asyncio
async def test_migration_creates_tbl_email_endpoint_details(test_db):
    """Details table exists with the two-token model + provider FKs."""
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_email_endpoint_details'
            """
        )
    )
    cols = {row[0] for row in result}
    expected = {
        "endpoint_id",
        "org_id",
        "forwarding_token",
        "reply_token",
        "domain_id",
        "smtp_sender_id",
        "oauth_account_id",
        "last_inbound_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


# ---------------------------------------------------------------------------
# Insert round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_insert_and_read_round_trip(test_db):
    org = await _make_org(test_db)
    endpoint = _make_endpoint(org_id=org.id)
    test_db.add(endpoint)
    await test_db.commit()
    await test_db.refresh(endpoint)

    assert endpoint.id is not None
    assert endpoint.channel == "email"
    assert endpoint.endpoint_type == "smtp_reply_capture"
    assert endpoint.is_active is True
    assert endpoint.deactivated_at is None


@pytest.mark.asyncio
async def test_details_insert_and_read_round_trip(test_db):
    org = await _make_org(test_db)
    endpoint = _make_endpoint(org_id=org.id)
    test_db.add(endpoint)
    await test_db.flush()

    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org.id,
        reply_token="tok-abc123def456",
    )
    test_db.add(details)
    await test_db.commit()
    await test_db.refresh(details)

    assert details.endpoint_id == endpoint.id
    assert details.reply_token == "tok-abc123def456"
    assert details.forwarding_token is None
    assert details.smtp_sender_id is None
    assert details.oauth_account_id is None
    assert details.domain_id is None
    assert details.last_inbound_at is None


# ---------------------------------------------------------------------------
# Constraints — CHECK, UNIQUE, cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_check_constraint_rejects_unknown_channel(test_db):
    """CHECK constraint blocks non-email channel values in v1."""
    org = await _make_org(test_db)
    endpoint = ChannelEndpoint(
        id=uuid.uuid4(),
        org_id=org.id,
        channel="whatsapp",  # not in the CHECK enum yet
        endpoint_type=ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
        label="x@example.com",
    )
    test_db.add(endpoint)
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_reply_token_unique_globally(test_db):
    """UNIQUE(reply_token) across all endpoints — collision rejected."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    ep_a = _make_endpoint(org_id=org_a.id)
    ep_b = _make_endpoint(org_id=org_b.id, label="b@example.com")
    test_db.add_all([ep_a, ep_b])
    await test_db.flush()

    d_a = EmailEndpointDetails(
        endpoint_id=ep_a.id,
        org_id=org_a.id,
        reply_token="shared-token-1234",
    )
    d_b = EmailEndpointDetails(
        endpoint_id=ep_b.id,
        org_id=org_b.id,
        reply_token="shared-token-1234",
    )
    test_db.add_all([d_a, d_b])
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_forwarding_token_unique_globally(test_db):
    """UNIQUE(forwarding_token) across all endpoints."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    ep_a = _make_endpoint(org_id=org_a.id, endpoint_type="forwarded_address")
    ep_b = _make_endpoint(
        org_id=org_b.id,
        endpoint_type="forwarded_address",
        label="b@example.com",
    )
    test_db.add_all([ep_a, ep_b])
    await test_db.flush()

    d_a = EmailEndpointDetails(
        endpoint_id=ep_a.id,
        org_id=org_a.id,
        forwarding_token="fwd-token-abcd",
    )
    d_b = EmailEndpointDetails(
        endpoint_id=ep_b.id,
        org_id=org_b.id,
        forwarding_token="fwd-token-abcd",
    )
    test_db.add_all([d_a, d_b])
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_details_cascade_on_endpoint_delete(test_db):
    """Deleting an endpoint cascades to its details row."""
    org = await _make_org(test_db)
    endpoint = _make_endpoint(org_id=org.id)
    test_db.add(endpoint)
    await test_db.flush()

    details = EmailEndpointDetails(
        endpoint_id=endpoint.id,
        org_id=org.id,
        reply_token="cascade-test-tok",
    )
    test_db.add(details)
    await test_db.commit()

    # Delete parent endpoint via raw SQL to bypass ORM-side eager loads.
    await test_db.execute(
        text("DELETE FROM tbl_channel_endpoints WHERE id = :id"),
        {"id": endpoint.id},
    )
    await test_db.commit()

    remaining = await test_db.execute(
        text("SELECT COUNT(*) FROM tbl_email_endpoint_details WHERE endpoint_id = :id"),
        {"id": endpoint.id},
    )
    assert remaining.scalar() == 0


@pytest.mark.asyncio
async def test_endpoint_cascade_on_org_delete(test_db):
    """Hard-deleting an org tears down its endpoints (CASCADE override)."""
    org = await _make_org(test_db)
    endpoint = _make_endpoint(org_id=org.id)
    test_db.add(endpoint)
    await test_db.commit()

    await test_db.execute(
        text("DELETE FROM tbl_organizations WHERE id = :id"),
        {"id": org.id},
    )
    await test_db.commit()

    remaining = await test_db.execute(
        text("SELECT COUNT(*) FROM tbl_channel_endpoints WHERE id = :id"),
        {"id": endpoint.id},
    )
    assert remaining.scalar() == 0


# ---------------------------------------------------------------------------
# Legacy column preservation (Track 1's zero-behavior-change guarantee)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_preserves_existing_inbound_token_column(test_db):
    """Track 1 must NOT touch tbl_email_smtp_senders.inbound_token.

    Removal is a follow-up track after every downstream caller migrates
    to EmailEndpointDetails.reply_token. This test guards against
    accidental drop.
    """
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_email_smtp_senders'
               AND column_name IN ('inbound_token', 'capture_replies_in_crm')
            """
        )
    )
    cols = {row[0] for row in result}
    assert cols == {"inbound_token", "capture_replies_in_crm"}


# ---------------------------------------------------------------------------
# Cross-org isolation via TenantScoped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_carries_org_id_column(test_db):
    """Endpoint row must expose org_id — RLS + TenantScoped depend on it."""
    inspector = inspect(ChannelEndpoint)
    assert "org_id" in {c.name for c in inspector.columns}


@pytest.mark.asyncio
async def test_details_carries_own_org_id_column(test_db):
    """Details row has its own org_id (RLS defense-in-depth)."""
    inspector = inspect(EmailEndpointDetails)
    assert "org_id" in {c.name for c in inspector.columns}


@pytest.mark.asyncio
async def test_two_orgs_endpoints_isolated_by_scan(test_db):
    """Bare SELECT scoped by org_id returns only that org's rows."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    test_db.add(_make_endpoint(org_id=org_a.id, label="a1@example.com"))
    test_db.add(_make_endpoint(org_id=org_a.id, label="a2@example.com"))
    test_db.add(_make_endpoint(org_id=org_b.id, label="b1@example.com"))
    await test_db.commit()

    a_rows = await test_db.execute(
        select(ChannelEndpoint).where(ChannelEndpoint.org_id == org_a.id)
    )
    b_rows = await test_db.execute(
        select(ChannelEndpoint).where(ChannelEndpoint.org_id == org_b.id)
    )
    assert len(a_rows.scalars().all()) == 2
    assert len(b_rows.scalars().all()) == 1
