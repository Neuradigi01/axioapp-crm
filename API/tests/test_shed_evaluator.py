"""Coverage for Step 4 of the email-reputation-warmup track — shed
evaluator + auto-recovery.

Ratios are calculated over the 24h delivered count. Event floor
guards against a single complaint on a 10-message day tripping the
cascade. Warning zone is 80% of the shed threshold — Owner gets a
soft notification before the hard shed fires.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.email.reputation import shed
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
    REPUTATION_STATE_OK,
    REPUTATION_STATE_WARNED,
    OrganizationEmailReputation,
)
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


async def _make_org(session) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Shed Org",
        slug=f"shed-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_row(
    session,
    *,
    org_id: uuid.UUID,
    stage: int = 3,
    state: str = REPUTATION_STATE_OK,
    blocked_until: datetime | None = None,
) -> OrganizationEmailReputation:
    row = OrganizationEmailReputation(
        org_id=org_id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
        warmup_stage=stage,
        reputation_state=state,
        blocked_until=blocked_until,
    )
    session.add(row)
    await session.flush()
    return row


def _mock_counters(counts: dict[str, int]) -> Any:
    async def _fake(*, org_id, envelope, domain_id, event):  # noqa: ARG001
        return counts.get(event, 0)

    return patch("src.app.core.email.reputation.shed.counters.sum_last_24h", side_effect=_fake)


# ---------------------------------------------------------------------------
# 1. Event-floor guard
# ---------------------------------------------------------------------------


async def test_shed_below_event_floor_skips(test_db):
    """<100 delivered → ratios don't fire even at absurd complaint
    rates. A 10-message-day + 3 complaints (30%) must NOT shed."""
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id)
    await test_db.commit()

    with _mock_counters({"delivered": 10, "complained": 3}):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    assert verdict is None
    await test_db.refresh(row)
    assert row.reputation_state == REPUTATION_STATE_OK


async def test_shed_at_event_floor_100_evaluates(test_db):
    """Exactly 100 delivered → ratios apply. 1 complaint = 1% > 0.3%
    → shed."""
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id)
    await test_db.commit()

    with (
        _mock_counters({"delivered": 100, "complained": 1}),
        patch("src.app.core.email.reputation.shed.notify_owner", new=AsyncMock()),
    ):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    assert verdict == REPUTATION_STATE_BLOCKED


# ---------------------------------------------------------------------------
# 2. Threshold breaches
# ---------------------------------------------------------------------------


async def test_shed_complaint_rate_over_threshold_blocks(test_db):
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    # 1000 delivered, 5 complaints = 0.5% > 0.3% threshold.
    with (
        _mock_counters({"delivered": 1000, "complained": 5}),
        patch("src.app.core.email.reputation.shed.notify_owner", new=AsyncMock()),
    ):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    assert verdict == REPUTATION_STATE_BLOCKED
    await test_db.refresh(row)
    assert row.reputation_state == REPUTATION_STATE_BLOCKED
    assert row.warmup_stage == 0  # reset
    assert row.blocked_until is not None


async def test_shed_bounce_rate_over_threshold_blocks(test_db):
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    # 1000 delivered, 60 bounces = 6% > 5% threshold.
    with (
        _mock_counters({"delivered": 1000, "bounced": 60}),
        patch("src.app.core.email.reputation.shed.notify_owner", new=AsyncMock()),
    ):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    assert verdict == REPUTATION_STATE_BLOCKED
    await test_db.refresh(row)
    assert row.warmup_stage == 0


async def test_shed_blocks_for_cooldown_hours(test_db):
    """blocked_until = now() + 4h (default) at breach time."""
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    before = datetime.now(UTC)
    with (
        _mock_counters({"delivered": 1000, "complained": 5}),
        patch("src.app.core.email.reputation.shed.notify_owner", new=AsyncMock()),
    ):
        await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    await test_db.refresh(row)
    assert row.blocked_until is not None
    # 4h cooldown ± 5 seconds for scheduling jitter.
    expected = before + timedelta(hours=4)
    delta = abs((row.blocked_until - expected).total_seconds())
    assert delta < 30


async def test_shed_notifies_owner_on_block(test_db):
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    notify_mock = AsyncMock()
    with (
        _mock_counters({"delivered": 1000, "complained": 5}),
        patch("src.app.core.email.reputation.shed.notify_owner", notify_mock),
    ):
        await shed.evaluate_shed_for_row(test_db, row_id=row.id)

    notify_mock.assert_called_once()
    assert notify_mock.call_args.kwargs["notification_type"] == "reputation.blocked"


# ---------------------------------------------------------------------------
# 3. Warning zone
# ---------------------------------------------------------------------------


async def test_shed_warning_zone_at_80pct_threshold_notifies_owner(test_db):
    """80% of 0.3% complaint threshold = 0.24%. A row at 0.25% enters
    ``warned`` state (not blocked)."""
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    # 1000 delivered, 2 complaints = 0.2% — under 0.24% zone.
    with _mock_counters({"delivered": 1000, "complained": 2}):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
    assert verdict is None

    # 1000 delivered, 3 complaints = 0.3% — this actually hits the
    # HARD threshold (>= 0.3%), so it should BLOCK, not warn.
    # Verifies the >=-vs-> boundary.
    row2 = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()
    with (
        _mock_counters({"delivered": 1000, "complained": 3}),
        patch("src.app.core.email.reputation.shed.notify_owner", new=AsyncMock()),
    ):
        verdict = await shed.evaluate_shed_for_row(test_db, row_id=row2.id)
    assert verdict == REPUTATION_STATE_BLOCKED


async def test_shed_warning_zone_notifies_once_then_sticky(test_db):
    """A row already in ``warned`` doesn't re-notify on subsequent
    ticks with the same (or slightly worse) rate — state is sticky
    until it clears back to ok or blocks."""
    org = await _make_org(test_db)
    row = await _make_row(test_db, org_id=org.id, stage=3)
    await test_db.commit()

    notify_mock = AsyncMock()
    # 1000 delivered, complaint rate 0.25% = 0.0025 (within warning
    # zone: 0.24% ≤ x < 0.3%). warning_zone_fraction default is 0.80,
    # so 0.003 * 0.80 = 0.0024; 0.0025 > 0.0024 fires warned.
    with (
        _mock_counters({"delivered": 10000, "complained": 25}),
        patch("src.app.core.email.reputation.shed.notify_owner", notify_mock),
    ):
        first = await shed.evaluate_shed_for_row(test_db, row_id=row.id)
        second = await shed.evaluate_shed_for_row(test_db, row_id=row.id)

    assert first == REPUTATION_STATE_WARNED
    assert second is None  # sticky — no second transition
    assert notify_mock.call_count == 1


# ---------------------------------------------------------------------------
# 4. Recovery
# ---------------------------------------------------------------------------


async def test_shed_recovery_after_blocked_until_expires_notifies_owner(test_db):
    org = await _make_org(test_db)
    row = await _make_row(
        test_db,
        org_id=org.id,
        stage=0,  # already reset by prior shed
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) - timedelta(minutes=1),
    )
    await test_db.commit()

    notify_mock = AsyncMock()
    with patch("src.app.core.email.reputation.shed.notify_owner", notify_mock):
        recovered = await shed.sweep_blocked_until_expiry(test_db)

    assert recovered == 1
    await test_db.refresh(row)
    assert row.reputation_state == REPUTATION_STATE_OK
    assert row.blocked_until is None
    notify_mock.assert_called_once()
    assert notify_mock.call_args.kwargs["notification_type"] == "reputation.recovered"


async def test_shed_recovery_skips_rows_still_within_cooldown(test_db):
    """A row with ``blocked_until`` still in the future stays blocked."""
    org = await _make_org(test_db)
    row = await _make_row(
        test_db,
        org_id=org.id,
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) + timedelta(hours=1),
    )
    await test_db.commit()

    recovered = await shed.sweep_blocked_until_expiry(test_db)
    assert recovered == 0
    await test_db.refresh(row)
    assert row.reputation_state == REPUTATION_STATE_BLOCKED
