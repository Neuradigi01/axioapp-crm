"""Coverage for the per-org usage counter table, service, and Celery tasks.

Tested through the function-scoped `test_db` fixture in `conftest.py`,
which builds the schema from `Base.metadata.create_all` against the
test DB. RLS policies are NOT applied in that path (only the migration
runtime calls `apply_rls`), so the cross-org isolation test exercises
the explicit `org_id` predicate rather than Postgres RLS.

Step-5 spec verifications covered:
  - `increment` creates a row on first call and stacks on subsequent.
  - Concurrent `increment` calls land an exact total (ON CONFLICT path).
  - `get` returns 0 for unknown / unseen resources.
  - `reset_monthly_counters` zeros monthly resources without touching
    lifetime ones.
  - The rollover Celery task advances `current_period_start/end` and
    inserts the new monthly rows.
  - `reset_daily_counters` opens the next day's row.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.app.core.subscriptions.models import Subscription, UsageCounter
from src.app.core.subscriptions.tasks import (
    _rollover_period_counters_async,
)
from src.app.core.subscriptions.usage_service import (
    RESOURCE_PERIOD_KIND,
    get,
    increment,
    reset_daily_counter_rows,
    reset_monthly_counters,
)
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_org(name: str = "Usage Co") -> Organization:
    return Organization(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")


def _make_active_sub(org_id: uuid.UUID) -> Subscription:
    now = datetime.now(tz=UTC)
    return Subscription(
        org_id=org_id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


@pytest_asyncio.fixture
async def org_with_sub(test_db):
    o = _make_org()
    test_db.add(o)
    await test_db.flush()
    test_db.add(_make_active_sub(o.id))
    await test_db.commit()
    return o


# ---------------------------------------------------------------------------
# increment / get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_creates_row_then_stacks(test_db, org_with_sub):
    v1 = await increment(test_db, org_with_sub.id, "contacts")
    await test_db.commit()
    assert v1 == 1

    v2 = await increment(test_db, org_with_sub.id, "contacts")
    await test_db.commit()
    assert v2 == 2

    rows = (
        (
            await test_db.execute(
                select(UsageCounter).where(
                    UsageCounter.org_id == org_with_sub.id,
                    UsageCounter.resource == "contacts",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1  # single row, value bumped twice
    assert rows[0].value == 2
    assert rows[0].period_kind == "lifetime"


@pytest.mark.asyncio
async def test_increment_accepts_delta(test_db, org_with_sub):
    v = await increment(test_db, org_with_sub.id, "contacts", delta=5)
    await test_db.commit()
    assert v == 5

    v2 = await increment(test_db, org_with_sub.id, "contacts", delta=-2)
    await test_db.commit()
    assert v2 == 3


@pytest.mark.asyncio
async def test_get_returns_zero_for_unseen_resource(test_db, org_with_sub):
    assert await get(test_db, org_with_sub.id, "contacts") == 0
    assert await get(test_db, org_with_sub.id, "leads_per_month") == 0


@pytest.mark.asyncio
async def test_get_returns_current_value(test_db, org_with_sub):
    await increment(test_db, org_with_sub.id, "contacts", delta=7)
    await test_db.commit()
    assert await get(test_db, org_with_sub.id, "contacts") == 7


@pytest.mark.asyncio
async def test_unknown_resource_raises(test_db, org_with_sub):
    with pytest.raises(KeyError):
        await increment(test_db, org_with_sub.id, "nope")
    with pytest.raises(KeyError):
        await get(test_db, org_with_sub.id, "nope")


# ---------------------------------------------------------------------------
# Period semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monthly_counter_keyed_to_subscription_period(test_db, org_with_sub):
    await increment(test_db, org_with_sub.id, "leads_per_month")
    await test_db.commit()
    row = (
        await test_db.execute(
            select(UsageCounter).where(
                UsageCounter.org_id == org_with_sub.id,
                UsageCounter.resource == "leads_per_month",
            )
        )
    ).scalar_one()
    sub = (
        await test_db.execute(select(Subscription).where(Subscription.org_id == org_with_sub.id))
    ).scalar_one()
    assert row.period_kind == "monthly"
    assert row.period_start == sub.current_period_start
    assert row.period_end == sub.current_period_end


@pytest.mark.asyncio
async def test_daily_counter_keyed_to_utc_day(test_db, org_with_sub):
    await increment(test_db, org_with_sub.id, "api_calls_per_day")
    await test_db.commit()
    row = (
        await test_db.execute(
            select(UsageCounter).where(
                UsageCounter.resource == "api_calls_per_day",
                UsageCounter.org_id == org_with_sub.id,
            )
        )
    ).scalar_one()
    assert row.period_kind == "daily"
    assert (row.period_end - row.period_start) == timedelta(days=1)


# ---------------------------------------------------------------------------
# Cross-org isolation (explicit predicate, RLS not active in tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_does_not_leak_across_orgs(test_db):
    a = _make_org("Org A")
    b = _make_org("Org B")
    test_db.add_all([a, b])
    await test_db.flush()
    test_db.add(_make_active_sub(a.id))
    test_db.add(_make_active_sub(b.id))
    await test_db.commit()

    await increment(test_db, a.id, "contacts", delta=10)
    await test_db.commit()
    assert await get(test_db, a.id, "contacts") == 10
    assert await get(test_db, b.id, "contacts") == 0


# ---------------------------------------------------------------------------
# reset_monthly_counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_monthly_does_not_touch_lifetime(test_db, org_with_sub):
    await increment(test_db, org_with_sub.id, "contacts", delta=100)
    await increment(test_db, org_with_sub.id, "leads_per_month", delta=50)
    await test_db.commit()

    now = datetime.now(tz=UTC)
    next_start = now + timedelta(days=30)
    next_end = next_start + timedelta(days=30)
    inserted = await reset_monthly_counters(test_db, org_with_sub.id, next_start, next_end)
    await test_db.commit()

    # One row per monthly resource in the taxonomy.
    monthly_resources = {r for r, k in RESOURCE_PERIOD_KIND.items() if k == "monthly"}
    assert inserted == len(monthly_resources)

    # contacts (lifetime) untouched.
    assert await get(test_db, org_with_sub.id, "contacts") == 100

    # The old `leads_per_month` row is still there for the previous
    # period (history). The new period row is at 0.
    new_row = (
        await test_db.execute(
            select(UsageCounter).where(
                UsageCounter.org_id == org_with_sub.id,
                UsageCounter.resource == "leads_per_month",
                UsageCounter.period_start == next_start,
            )
        )
    ).scalar_one()
    assert new_row.value == 0


@pytest.mark.asyncio
async def test_reset_monthly_is_idempotent(test_db, org_with_sub):
    now = datetime.now(tz=UTC)
    s = now + timedelta(days=30)
    e = s + timedelta(days=30)
    first = await reset_monthly_counters(test_db, org_with_sub.id, s, e)
    await test_db.commit()
    second = await reset_monthly_counters(test_db, org_with_sub.id, s, e)
    await test_db.commit()
    assert first > 0
    assert second == 0  # ON CONFLICT DO NOTHING


# ---------------------------------------------------------------------------
# Celery tasks (run the async impls directly to avoid Celery dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollover_advances_subscription_period(test_db):
    o = _make_org("Rollover Co")
    test_db.add(o)
    await test_db.flush()
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    sub = Subscription(
        org_id=o.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
        current_period_start=past - timedelta(days=30),
        current_period_end=past,
    )
    test_db.add(sub)
    await test_db.commit()

    summary = await _rollover_period_counters_async()
    assert summary["advanced"] >= 1

    refreshed = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    assert refreshed.current_period_end > datetime.now(tz=UTC)


@pytest.mark.asyncio
async def test_reset_daily_counter_rows_inserts_zero(test_db, org_with_sub):
    now = datetime.now(tz=UTC)
    tomorrow_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)
    inserted = await reset_daily_counter_rows(
        test_db, org_with_sub.id, tomorrow_start, tomorrow_end
    )
    await test_db.commit()
    assert inserted == 1  # only api_calls_per_day is daily

    row = (
        await test_db.execute(
            select(UsageCounter).where(
                UsageCounter.org_id == org_with_sub.id,
                UsageCounter.resource == "api_calls_per_day",
                UsageCounter.period_start == tomorrow_start,
            )
        )
    ).scalar_one()
    assert row.value == 0


# ---------------------------------------------------------------------------
# Concurrent increments (proves the ON CONFLICT DO UPDATE path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_increments_sum_correctly(org_with_sub):
    """50 concurrent bumps on independent sessions should land exactly 50."""
    from tests.conftest import TestSession

    org_id = org_with_sub.id

    async def _one():
        async with TestSession() as s:
            await increment(s, org_id, "contacts")
            await s.commit()

    await asyncio.gather(*(_one() for _ in range(50)))

    async with TestSession() as s:
        assert await get(s, org_id, "contacts") == 50
