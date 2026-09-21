"""Coverage for the ``tbl_organization_email_reputation`` migration
(Step 2 of tasks/email-reputation-warmup/).

Verifies the schema matches the README spec + the two partial unique
indexes correctly enforce single-platform_from-per-org + single-
own_domain-per-(org, domain) without treating the ``platform_from``
NULL ``domain_id`` as distinct across rows (Postgres' default UNIQUE
would).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
    REPUTATION_STATE_OK,
    OrganizationEmailReputation,
)
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Rep Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"rep-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_domain(session, *, org_id: uuid.UUID) -> OrganizationEmailDomain:
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=f"d-{uuid.uuid4().hex[:8]}.example",
        mailgun_domain_id="mg-x",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# 1. Schema — table + columns present
# ---------------------------------------------------------------------------


async def test_migration_creates_tbl_organization_email_reputation(test_db):
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_organization_email_reputation'
            """
        )
    )
    cols = {row[0] for row in result}
    expected = {
        "id",
        "org_id",
        "envelope_type",
        "domain_id",
        "warmup_stage",
        "warmup_stage_earned_at",
        "warmup_stage_current_sent",
        "daily_sent_count",
        "daily_reset_at",
        "bounce_count_24h",
        "complaint_count_24h",
        "delivered_count_24h",
        "reputation_state",
        "blocked_until",
        "updated_at",
    }
    missing = expected - cols
    assert not missing, f"columns missing: {missing}"


# ---------------------------------------------------------------------------
# 2. Uniqueness — the load-bearing partial indexes
# ---------------------------------------------------------------------------


async def test_migration_unique_constraint_platform_from_one_per_org(test_db):
    """Two ``platform_from`` rows for the SAME org must not both land
    — despite both carrying NULL ``domain_id``. Postgres default
    UNIQUE would let both through; the partial index catches this."""
    org = await _make_org(test_db)
    first = OrganizationEmailReputation(
        org_id=org.id, envelope_type=ENVELOPE_TYPE_PLATFORM_FROM, domain_id=None
    )
    test_db.add(first)
    await test_db.flush()

    second = OrganizationEmailReputation(
        org_id=org.id, envelope_type=ENVELOPE_TYPE_PLATFORM_FROM, domain_id=None
    )
    test_db.add(second)
    with pytest.raises(IntegrityError):
        await test_db.commit()


async def test_migration_unique_constraint_own_domain_one_per_org_domain(
    test_db,
):
    org = await _make_org(test_db)
    domain = await _make_domain(test_db, org_id=org.id)
    await test_db.commit()

    first = OrganizationEmailReputation(
        org_id=org.id, envelope_type=ENVELOPE_TYPE_OWN_DOMAIN, domain_id=domain.id
    )
    test_db.add(first)
    await test_db.flush()

    second = OrganizationEmailReputation(
        org_id=org.id, envelope_type=ENVELOPE_TYPE_OWN_DOMAIN, domain_id=domain.id
    )
    test_db.add(second)
    with pytest.raises(IntegrityError):
        await test_db.commit()


async def test_migration_platform_from_and_own_domain_coexist_for_same_org(
    test_db,
):
    """The partial indexes are envelope-scoped — a ``platform_from``
    row and an ``own_domain`` row can coexist for the same org."""
    org = await _make_org(test_db)
    domain = await _make_domain(test_db, org_id=org.id)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
        )
    )
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
            domain_id=domain.id,
        )
    )
    await test_db.commit()

    rows = (
        (
            await test_db.execute(
                select(OrganizationEmailReputation).where(
                    OrganizationEmailReputation.org_id == org.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# 3. CHECK constraints
# ---------------------------------------------------------------------------


async def test_migration_check_constraint_envelope_type(test_db):
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailReputation(org_id=org.id, envelope_type="something_else", domain_id=None)
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()


async def test_migration_check_constraint_reputation_state(test_db):
    org = await _make_org(test_db)
    row = OrganizationEmailReputation(
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
    )
    row.reputation_state = "quarantined"  # not in enum
    test_db.add(row)
    with pytest.raises(IntegrityError):
        await test_db.commit()


async def test_migration_check_envelope_domain_shape_platform_from_requires_null_domain(
    test_db,
):
    """A ``platform_from`` row with a non-null ``domain_id`` is a
    logically-impossible shape — pair-CHECK rejects it."""
    org = await _make_org(test_db)
    domain = await _make_domain(test_db, org_id=org.id)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=domain.id,  # wrong — platform_from must be NULL
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()


async def test_migration_check_envelope_domain_shape_own_domain_requires_domain(
    test_db,
):
    """Own-domain row with NULL ``domain_id`` is rejected by the
    pair-CHECK."""
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
            domain_id=None,  # wrong — own_domain must carry a domain
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()


# ---------------------------------------------------------------------------
# 4. Round-trip + defaults
# ---------------------------------------------------------------------------


async def test_insert_round_trip_uses_server_defaults(test_db):
    org = await _make_org(test_db)
    row = OrganizationEmailReputation(
        org_id=org.id, envelope_type=ENVELOPE_TYPE_PLATFORM_FROM, domain_id=None
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)
    assert row.warmup_stage == 0
    assert row.warmup_stage_current_sent == 0
    assert row.daily_sent_count == 0
    assert row.bounce_count_24h == 0
    assert row.complaint_count_24h == 0
    assert row.delivered_count_24h == 0
    assert row.reputation_state == REPUTATION_STATE_OK
    assert row.blocked_until is None


# ---------------------------------------------------------------------------
# 5. Cascade on org delete
# ---------------------------------------------------------------------------


async def test_org_delete_cascades_to_reputation_rows(test_db):
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
            reputation_state=REPUTATION_STATE_BLOCKED,
        )
    )
    await test_db.commit()

    await test_db.execute(text("DELETE FROM tbl_organizations WHERE id = :id"), {"id": org.id})
    await test_db.commit()

    remaining = await test_db.execute(
        text("SELECT COUNT(*) FROM tbl_organization_email_reputation WHERE org_id = :id"),
        {"id": org.id},
    )
    assert remaining.scalar() == 0
