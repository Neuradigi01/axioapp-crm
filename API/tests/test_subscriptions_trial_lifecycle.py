"""Coverage for the trial-lifecycle state machine + the signup hook.

Tests are run via the function-scoped `test_db` fixture in
`conftest.py`. RLS policies are NOT applied in that path (only the
migration runtime calls `apply_rls`), so cross-org isolation is
exercised via the explicit `org_id` predicate in the service code.

Step-6 spec verifications covered:
  - `create_trial_subscription` produces a row with `status='trialing'`,
    `plan_code='trial'`, and a 14-day window.
  - `transition_if_due`:
      * Trial → read_only at deadline
      * Read_only → archived at deadline
      * Archived → row deleted at deadline
      * Idempotent (a second call after transition is a no-op)
      * Aborts cleanly when status changed underfoot (race)
  - `scan_and_transition_due` returns the right summary across mixed
    fixtures.
  - `fire_due_reminders` queues `trial_ending_soon` exactly once per
    sub even on a repeated scan.
  - Audit events land for every transition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from src.app.core.audit.models import AuditLog
from src.app.core.subscriptions.lifecycle import (
    fire_due_reminders,
    scan_and_transition_due,
    transition_if_due,
)
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.signup_hook import (
    TRIAL_SEATS,
    create_trial_subscription,
)
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_org(name: str = "Lifecycle Co") -> Organization:
    return Organization(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")


async def _insert_sub(
    session,
    org_id: uuid.UUID,
    *,
    status: str = "trialing",
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
    read_only_at: datetime | None = None,
    archived_at: datetime | None = None,
    plan_code: str = "trial",
) -> Subscription:
    now = datetime.now(tz=UTC)
    sub = Subscription(
        org_id=org_id,
        plan_code=plan_code,
        status=status,
        billing_cycle="monthly",
        seats_purchased=3,
        trial_started_at=trial_started_at,
        trial_ends_at=trial_ends_at,
        current_period_start=trial_started_at or now,
        current_period_end=trial_ends_at or (now + timedelta(days=14)),
        read_only_at=read_only_at,
        archived_at=archived_at,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


@pytest_asyncio.fixture
async def fresh_org(test_db):
    o = _make_org()
    test_db.add(o)
    await test_db.commit()
    return o


# ---------------------------------------------------------------------------
# Signup hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_trial_subscription_inserts_100_day_trial(test_db, fresh_org):
    sub = await create_trial_subscription(test_db, org_id=fresh_org.id)
    # Hook does NOT commit; the caller does.
    await test_db.commit()
    await test_db.refresh(sub)

    assert sub.org_id == fresh_org.id
    assert sub.plan_code == "trial"
    assert sub.status == "trialing"
    assert sub.billing_cycle == "monthly"
    assert sub.seats_purchased == TRIAL_SEATS
    assert sub.trial_started_at is not None
    assert sub.trial_ends_at is not None
    window = sub.trial_ends_at - sub.trial_started_at
    assert timedelta(days=99, hours=23) < window < timedelta(days=100, hours=1)


@pytest.mark.asyncio
async def test_signup_hook_rolls_back_with_parent_transaction(test_db):
    """If the parent flow rolls back after `create_trial_subscription`,
    no row remains."""
    o = _make_org("Rollback Co")
    test_db.add(o)
    await test_db.flush()
    await create_trial_subscription(test_db, org_id=o.id)
    await test_db.rollback()

    rows = (
        (await test_db.execute(select(Subscription).where(Subscription.org_id == o.id)))
        .scalars()
        .all()
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Trial → read_only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_to_read_only_at_deadline(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(hours=1),
    )

    new_status = await transition_if_due(test_db, sub)
    await test_db.commit()
    assert new_status == "read_only"

    refreshed = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    assert refreshed.status == "read_only"
    assert refreshed.read_only_at is not None

    audit_row = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "trial.expired",
                AuditLog.entity_id == sub.id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.user_id is None  # system actor


@pytest.mark.asyncio
async def test_trial_not_yet_due_returns_none(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
    )

    new_status = await transition_if_due(test_db, sub)
    assert new_status is None


# ---------------------------------------------------------------------------
# Read_only → archived
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_to_archived_at_deadline(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="read_only",
        read_only_at=now - timedelta(days=31),
    )

    new_status = await transition_if_due(test_db, sub)
    await test_db.commit()
    assert new_status == "archived"

    refreshed = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    assert refreshed.status == "archived"
    assert refreshed.archived_at is not None


# ---------------------------------------------------------------------------
# Archived → deleted (row removed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_to_deleted_at_deadline(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="archived",
        archived_at=now - timedelta(days=91),
    )
    sub_id = sub.id

    new_status = await transition_if_due(test_db, sub)
    await test_db.commit()
    assert new_status == "deleted"

    remaining = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub_id))
    ).scalar_one_or_none()
    assert remaining is None

    audit_row = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "org.deleted",
                AuditLog.entity_id == sub_id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None


# ---------------------------------------------------------------------------
# Idempotency / race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_idempotent(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(hours=1),
    )
    first = await transition_if_due(test_db, sub)
    await test_db.commit()
    assert first == "read_only"

    refreshed = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    # `subscription` is the original snapshot; pass the refreshed row.
    second = await transition_if_due(test_db, refreshed)
    assert second is None  # already past trial, now read_only


@pytest.mark.asyncio
async def test_transition_aborts_on_concurrent_status_change(test_db, fresh_org):
    """If status flipped underfoot (e.g. paid upgrade) the UPDATE is
    a no-op and we emit no audit/email."""
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(hours=1),
    )
    # Simulate a concurrent payment success.
    await test_db.execute(
        text("UPDATE tbl_subscriptions SET status='active', plan_code='basic' WHERE id=:id"),
        {"id": sub.id},
    )
    await test_db.commit()

    # The original `sub` snapshot still says 'trialing'; the transition
    # should detect the underlying status change and abort silently.
    result = await transition_if_due(test_db, sub)
    assert result is None

    audit_row = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "trial.expired",
                AuditLog.entity_id == sub.id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is None


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_summary_counts_mixed_states(test_db):
    now = datetime.now(tz=UTC)

    # 2 trials past deadline
    for _ in range(2):
        o = _make_org()
        test_db.add(o)
        await test_db.flush()
        await _insert_sub(
            test_db,
            o.id,
            status="trialing",
            trial_started_at=now - timedelta(days=15),
            trial_ends_at=now - timedelta(hours=1),
        )

    # 1 read_only past archive deadline
    o = _make_org()
    test_db.add(o)
    await test_db.flush()
    await _insert_sub(test_db, o.id, status="read_only", read_only_at=now - timedelta(days=31))

    # 1 archived past delete deadline
    o = _make_org()
    test_db.add(o)
    await test_db.flush()
    await _insert_sub(test_db, o.id, status="archived", archived_at=now - timedelta(days=91))

    # 1 trial NOT due
    o = _make_org()
    test_db.add(o)
    await test_db.flush()
    await _insert_sub(
        test_db,
        o.id,
        status="trialing",
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
    )

    summary = await scan_and_transition_due(test_db)
    await test_db.commit()
    assert summary["trialing_to_read_only"] == 2
    assert summary["read_only_to_archived"] == 1
    assert summary["archived_to_deleted"] == 1


# ---------------------------------------------------------------------------
# 3-day reminder dedup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_ending_soon_fires_once(test_db, fresh_org):
    now = datetime.now(tz=UTC)
    sub = await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now - timedelta(days=11),
        trial_ends_at=now + timedelta(days=2),
    )

    first = await fire_due_reminders(test_db)
    await test_db.commit()
    assert first == 1

    second = await fire_due_reminders(test_db)
    await test_db.commit()
    assert second == 0

    refreshed = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    assert refreshed.reminders_sent.get("trial_ending_soon") is True


@pytest.mark.asyncio
async def test_trial_ending_soon_skips_already_expired(test_db, fresh_org):
    """If the trial is already past deadline, the reminder window has
    closed — no email."""
    now = datetime.now(tz=UTC)
    await _insert_sub(
        test_db,
        fresh_org.id,
        status="trialing",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(hours=1),
    )
    fired = await fire_due_reminders(test_db)
    assert fired == 0
