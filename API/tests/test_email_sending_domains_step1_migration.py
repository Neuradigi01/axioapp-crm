"""Coverage for Step 1 of tasks/email-sending-domains/.

Verifies the ``tbl_organization_email_domains`` schema against the ORM
class declared in ``core/email_sender_setup/models.py``.

Test-DB behaviour: :func:`conftest.test_db` calls
``Base.metadata.create_all`` per test, so every model column, index,
and constraint is created fresh. The migration file itself
(``0233_email_domains``) is the source-of-truth for the live DB;
these tests lock the ORM/migration parity via CI schema-drift checks.

Backfill: N/A for this table (net-new; no existing rows to migrate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_RELEASED,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_org(session, name: str = "Domains Org") -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"dom-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


def _make_domain(
    *,
    org_id: uuid.UUID,
    domain: str = "acme.example",
    mailgun_domain_id: str = "mg-12345",
    verification_status: str = VERIFICATION_STATUS_PENDING,
    dns_records: dict | None = None,
    region: str = "us",
) -> OrganizationEmailDomain:
    return OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id=mailgun_domain_id,
        verification_status=verification_status,
        dns_records=dns_records or {},
        region=region,
    )


# ---------------------------------------------------------------------------
# Schema — table + columns present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_tbl_organization_email_domains(test_db):
    result = await test_db.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'tbl_organization_email_domains'
            """
        )
    )
    cols = {row[0] for row in result}
    expected = {
        "id",
        "org_id",
        "domain",
        "mailgun_domain_id",
        "verification_status",
        "dns_records",
        "mx_verified",
        "spf_verified",
        "dkim_verified",
        "dmarc_verified",
        "last_verified_at",
        "consecutive_failed_checks",
        "demoted_at",
        "released_at",
        "region",
        "created_at",
        "updated_at",
    }
    missing = expected - cols
    assert not missing, f"columns missing: {missing}"


# ---------------------------------------------------------------------------
# Round-trip insert + JSONB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_round_trip_stores_dns_records_verbatim(test_db):
    """JSONB column stores Mailgun's response shape without transformation."""
    org = await _make_org(test_db)
    mailgun_response_verbatim = {
        "sending": [
            {
                "record_type": "TXT",
                "name": "smtp._domainkey.acme.example",
                "value": "v=DKIM1; k=rsa; p=MIIB...",
                "priority": None,
                "valid": "valid",
                "cached": [],
                "is_active": True,
            },
            {
                "record_type": "TXT",
                "name": "acme.example",
                "value": "v=spf1 include:mailgun.org ~all",
                "priority": None,
                "valid": "valid",
                "cached": [],
                "is_active": True,
            },
        ],
        "receiving": [
            {
                "record_type": "MX",
                "name": "acme.example",
                "value": "mxa.mailgun.org",
                "priority": "10",
                "valid": "unknown",
                "cached": [],
                "is_active": True,
            },
        ],
    }
    row = _make_domain(
        org_id=org.id,
        dns_records=mailgun_response_verbatim,
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)

    # Verbatim round-trip.
    assert row.dns_records == mailgun_response_verbatim
    assert row.dns_records["sending"][0]["record_type"] == "TXT"
    assert row.dns_records["receiving"][0]["priority"] == "10"
    # Server defaults.
    assert row.verification_status == VERIFICATION_STATUS_PENDING
    assert row.region == "us"
    assert row.consecutive_failed_checks == 0
    assert row.mx_verified is False


# ---------------------------------------------------------------------------
# Constraints — CHECK + UNIQUE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_unique_globally(test_db):
    """A domain string belongs to at most one org."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    d_a = _make_domain(org_id=org_a.id, domain="collision.example")
    d_b = _make_domain(org_id=org_b.id, domain="collision.example")
    test_db.add_all([d_a, d_b])
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_verification_status_check_rejects_unknown_value(test_db):
    org = await _make_org(test_db)
    row = _make_domain(
        org_id=org.id,
        verification_status="quarantined",  # not in enum
    )
    test_db.add(row)
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_region_check_rejects_unknown_value(test_db):
    org = await _make_org(test_db)
    row = _make_domain(org_id=org.id, region="ap")  # not in enum
    test_db.add(row)
    with pytest.raises(IntegrityError):
        await test_db.commit()


@pytest.mark.asyncio
async def test_consecutive_failed_checks_check_rejects_negative(test_db):
    org = await _make_org(test_db)
    row = _make_domain(org_id=org.id)
    row.consecutive_failed_checks = -1
    test_db.add(row)
    with pytest.raises(IntegrityError):
        await test_db.commit()


# ---------------------------------------------------------------------------
# is_operational property — send-cascade helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_operational_true_only_when_verified(test_db):
    org = await _make_org(test_db)
    for status, expected in (
        (VERIFICATION_STATUS_PENDING, False),
        (VERIFICATION_STATUS_VERIFIED, True),
        (VERIFICATION_STATUS_DEMOTED, False),
        (VERIFICATION_STATUS_RELEASED, False),
    ):
        row = _make_domain(
            org_id=org.id,
            domain=f"is-op-{status}.example",
            verification_status=status,
        )
        assert row.is_operational is expected, f"status={status}"


# ---------------------------------------------------------------------------
# Cross-org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_isolated_by_org_id_filter(test_db):
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    test_db.add(_make_domain(org_id=org_a.id, domain="a-only.example"))
    test_db.add(_make_domain(org_id=org_b.id, domain="b-only.example"))
    await test_db.commit()

    a_rows = await test_db.execute(
        select(OrganizationEmailDomain).where(
            OrganizationEmailDomain.org_id == org_a.id
        )
    )
    b_rows = await test_db.execute(
        select(OrganizationEmailDomain).where(
            OrganizationEmailDomain.org_id == org_b.id
        )
    )
    assert len(a_rows.scalars().all()) == 1
    assert len(b_rows.scalars().all()) == 1


# ---------------------------------------------------------------------------
# Cascade on org delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_delete_cascades_to_domain_rows(test_db):
    org = await _make_org(test_db)
    row = _make_domain(org_id=org.id, domain="cascade.example")
    test_db.add(row)
    await test_db.commit()

    await test_db.execute(
        text("DELETE FROM tbl_organizations WHERE id = :id"), {"id": org.id}
    )
    await test_db.commit()

    remaining = await test_db.execute(
        text(
            "SELECT COUNT(*) FROM tbl_organization_email_domains WHERE org_id = :id"
        ),
        {"id": org.id},
    )
    assert remaining.scalar() == 0


# ---------------------------------------------------------------------------
# Column type sanity
# ---------------------------------------------------------------------------


def test_orm_column_types_match_migration():
    inspector = inspect(OrganizationEmailDomain)
    cols = {c.name: c for c in inspector.columns}
    # JSONB
    assert "dns_records" in cols
    # Enum-status stored as string not native ENUM (per DISCOVERY-NOTES)
    assert cols["verification_status"].type.python_type is str
    assert cols["region"].type.python_type is str
