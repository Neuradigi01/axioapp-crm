"""Coverage for the `subscriptions` table — model constraints, the
partial unique active-per-org invariant, and the `get_active_subscription`
service helper.

Notes on what is NOT covered here:
  - RLS policies: the test conftest builds the schema from
    `Base.metadata.create_all`, not from the Alembic migration, so the
    `apply_rls(...)` policies do not exist on the test DB. Live-DB
    smoke (after `run.cmd upgrade`) verifies isolation.
  - Backfill: same reason. The backfill INSERT runs only on the real
    migration. Smoke verifies one row per `organizations` row.
  - Downgrade: tested via the run.cmd smoke loop in the step
    report (`downgrade -1` then `upgrade head`), not as a pytest case.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.app.core.subscriptions.models import (
    ACTIVE_STATUSES,
    SUBSCRIPTION_STATUSES,
    Subscription,
)
from src.app.core.subscriptions.service import get_active_subscription
from src.app.core.tenants.models import Organization


def _make_org(name: str, slug: str) -> Organization:
    return Organization(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
    )


def _make_sub(
    org_id: uuid.UUID,
    *,
    plan_code: str = "trial",
    status: str = "trialing",
    billing_cycle: str = "monthly",
    seats_purchased: int = 3,
) -> Subscription:
    now = datetime.now(tz=UTC)
    return Subscription(
        org_id=org_id,
        plan_code=plan_code,
        status=status,
        billing_cycle=billing_cycle,
        seats_purchased=seats_purchased,
        trial_started_at=now if status == "trialing" else None,
        trial_ends_at=now + timedelta(days=14) if status == "trialing" else None,
        current_period_start=now,
        current_period_end=now + timedelta(days=14),
    )


@pytest_asyncio.fixture
async def org(test_db):
    o = _make_org("Acme", f"acme-{uuid.uuid4().hex[:6]}")
    test_db.add(o)
    await test_db.commit()
    await test_db.refresh(o)
    return o


# ---------------------------------------------------------------------------
# Table shape — columns, defaults, FK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_and_read(test_db, org):
    sub = _make_sub(org.id)
    test_db.add(sub)
    await test_db.commit()
    await test_db.refresh(sub)

    assert sub.id is not None
    assert sub.org_id == org.id
    assert sub.plan_code == "trial"
    assert sub.status == "trialing"
    assert sub.billing_cycle == "monthly"
    assert sub.seats_purchased == 3
    assert sub.created_at is not None
    assert sub.updated_at is not None
    assert sub.trial_ends_at is not None
    assert sub.stripe_customer_id is None


@pytest.mark.asyncio
async def test_org_id_fk_required(test_db):
    """Inserting without a valid org_id fails the FK."""
    sub = Subscription(
        org_id=uuid.uuid4(),  # not in organizations
        plan_code="trial",
        status="trialing",
        billing_cycle="monthly",
        seats_purchased=3,
        current_period_start=datetime.now(tz=UTC),
        current_period_end=datetime.now(tz=UTC) + timedelta(days=14),
    )
    test_db.add(sub)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_check_rejects_gibberish(test_db, org):
    sub = _make_sub(org.id, status="gibberish")
    test_db.add(sub)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_billing_cycle_check_rejects_unknown_value(test_db, org):
    # `weekly` fits inside the VARCHAR(8) column (so it reaches the CHECK
    # constraint rather than tripping a string-truncation error first)
    # and is not in {monthly, annual}.
    sub = _make_sub(org.id, billing_cycle="weekly")
    test_db.add(sub)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_seats_positive_check_rejects_zero(test_db, org):
    sub = _make_sub(org.id, seats_purchased=0)
    test_db.add(sub)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_all_canonical_statuses_accepted(test_db, org):
    """Every status in SUBSCRIPTION_STATUSES is accepted by the CHECK.

    Inserts are split across separate orgs so the partial unique index
    does not collide (multiple active rows on one org are forbidden).
    """
    for i, status in enumerate(SUBSCRIPTION_STATUSES):
        o = _make_org(f"Org-{status}-{i}", f"org-{status}-{i}-{uuid.uuid4().hex[:6]}")
        test_db.add(o)
        await test_db.commit()
        sub = _make_sub(o.id, status=status)
        test_db.add(sub)
        await test_db.commit()
        await test_db.refresh(sub)
        assert sub.status == status


# ---------------------------------------------------------------------------
# Partial unique index — one active subscription per org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_active_subscription_rejected(test_db, org):
    """Two `trialing` rows for the same org violate the partial unique
    index."""
    sub_a = _make_sub(org.id, status="trialing")
    test_db.add(sub_a)
    await test_db.commit()

    sub_b = _make_sub(org.id, status="trialing")
    test_db.add(sub_b)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_multiple_archived_subscriptions_allowed(test_db, org):
    """`archived` rows are history and do not stack into the partial
    unique index — multiple archived rows per org are fine."""
    sub_a = _make_sub(org.id, status="archived")
    test_db.add(sub_a)
    await test_db.commit()

    sub_b = _make_sub(org.id, status="archived")
    test_db.add(sub_b)
    await test_db.commit()  # should succeed

    result = await test_db.execute(select(Subscription).where(Subscription.org_id == org.id))
    rows = list(result.scalars())
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_active_plus_archived_coexist(test_db, org):
    """One active row + multiple archived/cancelled rows on the same
    org is the steady state after an upgrade-cancel-upgrade cycle."""
    test_db.add(_make_sub(org.id, status="archived"))
    test_db.add(_make_sub(org.id, status="cancelled"))
    await test_db.commit()
    test_db.add(_make_sub(org.id, status="active", plan_code="standard"))
    await test_db.commit()  # should succeed
    test_db.add(_make_sub(org.id, status="trialing"))
    with pytest.raises(IntegrityError):
        # but a SECOND active-set row fails
        await test_db.commit()
    await test_db.rollback()


# ---------------------------------------------------------------------------
# `get_active_subscription` service helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_returns_trialing_row(test_db, org):
    sub = _make_sub(org.id, status="trialing")
    test_db.add(sub)
    await test_db.commit()

    found = await get_active_subscription(test_db, org.id)
    assert found is not None
    assert found.id == sub.id
    assert found.status == "trialing"


@pytest.mark.asyncio
async def test_get_active_returns_none_when_only_archived(test_db, org):
    test_db.add(_make_sub(org.id, status="archived"))
    test_db.add(_make_sub(org.id, status="cancelled"))
    await test_db.commit()

    found = await get_active_subscription(test_db, org.id)
    assert found is None


@pytest.mark.asyncio
async def test_get_active_returns_none_for_unknown_org(test_db, org):
    test_db.add(_make_sub(org.id, status="trialing"))
    await test_db.commit()

    found = await get_active_subscription(test_db, uuid.uuid4())
    assert found is None


@pytest.mark.asyncio
async def test_get_active_returns_read_only_row(test_db, org):
    """`read_only` is part of the active set — `get_active_subscription`
    must return it so the billing page can render the upgrade prompt."""
    sub = _make_sub(org.id, status="read_only")
    sub.read_only_at = datetime.now(tz=UTC)
    test_db.add(sub)
    await test_db.commit()

    found = await get_active_subscription(test_db, org.id)
    assert found is not None
    assert found.status == "read_only"


# ---------------------------------------------------------------------------
# Constants alignment — guards against drift between models / migration
# ---------------------------------------------------------------------------


def test_active_statuses_subset_of_all_statuses():
    for s in ACTIVE_STATUSES:
        assert s in SUBSCRIPTION_STATUSES


def test_active_statuses_excludes_terminal():
    assert "archived" not in ACTIVE_STATUSES
    assert "cancelled" not in ACTIVE_STATUSES
