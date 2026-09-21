"""Coverage for Step 4 of the email-reputation-warmup track — the
warmup ladder advance.

The evaluator reads 24h event counts from Redis (faked here) + the
row's current stage from Postgres. Advance rule: total_events >=
stage_cap * earn_fraction AND thresholds under.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from src.app.core.email.reputation import warmup
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
    OrganizationEmailReputation,
)
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


async def _make_org(session, name: str = "Warmup Org") -> Organization:
    org = Organization(id=uuid.uuid4(), name=name, slug=f"warm-{uuid.uuid4().hex[:8]}")
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


async def _make_reputation_row(
    session,
    *,
    org_id: uuid.UUID,
    stage: int = 0,
    envelope: str = ENVELOPE_TYPE_PLATFORM_FROM,
    domain_id: uuid.UUID | None = None,
    state: str = "ok",
) -> OrganizationEmailReputation:
    row = OrganizationEmailReputation(
        org_id=org_id,
        envelope_type=envelope,
        domain_id=domain_id,
        warmup_stage=stage,
        reputation_state=state,
    )
    session.add(row)
    await session.flush()
    return row


def _mock_counters(counts: dict[str, int]) -> Any:
    """Patch ``counters.sum_last_24h`` to return the caller-specified
    counts by event kind. Missing keys → 0."""

    async def _fake(*, org_id, envelope, domain_id, event):  # noqa: ARG001
        return counts.get(event, 0)

    return patch(
        "src.app.core.email.reputation.warmup.counters.sum_last_24h",
        side_effect=_fake,
    )


async def test_warmup_advance_after_50pct_sent_under_thresholds(test_db, monkeypatch):
    """Stage 0 cap = 50. Earn fraction 0.5 → 25 delivered under
    thresholds advances to stage 1."""
    org = await _make_org(test_db)
    row = await _make_reputation_row(test_db, org_id=org.id, stage=0)
    await test_db.commit()

    with (
        _mock_counters({"delivered": 25}),
        patch(
            "src.app.core.email.reputation.warmup.notify_owner",
            new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(),
        ),
    ):
        advanced = await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)
    assert advanced is True
    await test_db.refresh(row)
    assert row.warmup_stage == 1
    assert row.warmup_stage_current_sent == 0
    assert row.warmup_stage_earned_at is not None


async def test_warmup_does_not_advance_below_earn_fraction(test_db):
    org = await _make_org(test_db)
    row = await _make_reputation_row(test_db, org_id=org.id, stage=0)
    await test_db.commit()

    with _mock_counters({"delivered": 24}):  # 24 < 50 * 0.5 = 25
        advanced = await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)
    assert advanced is False
    await test_db.refresh(row)
    assert row.warmup_stage == 0


async def test_warmup_does_not_advance_when_complaint_threshold_breached(
    test_db,
):
    """Row met the earn fraction but complaint rate ≥ 0.3% (default).
    Advance is blocked so the shed evaluator (same tick) can fire."""
    org = await _make_org(test_db)
    row = await _make_reputation_row(test_db, org_id=org.id, stage=0)
    await test_db.commit()

    # 1000 delivered, 5 complaints = 0.5% > 0.3% threshold.
    with _mock_counters({"delivered": 1000, "complained": 5}):
        advanced = await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)
    assert advanced is False


async def test_warmup_does_not_advance_when_bounce_threshold_breached(test_db):
    org = await _make_org(test_db)
    row = await _make_reputation_row(test_db, org_id=org.id, stage=0)
    await test_db.commit()

    # 1000 delivered, 60 bounces = 6% > 5% threshold.
    with _mock_counters({"delivered": 1000, "bounced": 60}):
        advanced = await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)
    assert advanced is False


async def test_warmup_does_not_advance_blocked_row(test_db):
    """A row in ``blocked`` state is not eligible for advance —
    recovery flow (shed.sweep_blocked_until_expiry) is the only path
    out of blocked."""
    org = await _make_org(test_db)
    row = await _make_reputation_row(
        test_db, org_id=org.id, stage=0, state=REPUTATION_STATE_BLOCKED
    )
    await test_db.commit()

    with _mock_counters({"delivered": 1000}):
        advanced = await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)
    assert advanced is False


async def test_warmup_platform_from_and_own_domain_advance_independently(test_db):
    """One org can have two rows — platform_from at stage 0, own_domain
    at stage 3 — and warmup advances each independently."""
    org = await _make_org(test_db)
    domain = await _make_domain(test_db, org_id=org.id)
    pf_row = await _make_reputation_row(
        test_db, org_id=org.id, envelope=ENVELOPE_TYPE_PLATFORM_FROM, stage=0
    )
    od_row = await _make_reputation_row(
        test_db,
        org_id=org.id,
        envelope=ENVELOPE_TYPE_OWN_DOMAIN,
        domain_id=domain.id,
        stage=3,
    )
    await test_db.commit()

    # 26 delivered → advance platform_from (cap 50, earn 25).
    with (
        _mock_counters({"delivered": 26}),
        patch(
            "src.app.core.email.reputation.warmup.notify_owner",
            new_callable=lambda: __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(),
        ),
    ):
        assert await warmup.evaluate_warmup_for_row(test_db, row_id=pf_row.id) is True
        # own_domain at stage 3 (cap 5000) needs 2500 → 26 is not enough.
        assert await warmup.evaluate_warmup_for_row(test_db, row_id=od_row.id) is False

    await test_db.refresh(pf_row)
    await test_db.refresh(od_row)
    assert pf_row.warmup_stage == 1
    assert od_row.warmup_stage == 3


async def test_warmup_notify_owner_on_advance(test_db):
    """Advance action fires the Owner in-app notification with the
    new stage + cap in the payload."""
    org = await _make_org(test_db)
    row = await _make_reputation_row(test_db, org_id=org.id, stage=0)
    await test_db.commit()

    from unittest.mock import AsyncMock

    notify_mock = AsyncMock()
    with (
        _mock_counters({"delivered": 30}),
        patch("src.app.core.email.reputation.warmup.notify_owner", notify_mock),
    ):
        await warmup.evaluate_warmup_for_row(test_db, row_id=row.id)

    notify_mock.assert_called_once()
    call = notify_mock.call_args
    assert call.kwargs["notification_type"] == "reputation.warmup_advanced"
    assert call.kwargs["payload"]["warmup_stage"] == 1
    assert call.kwargs["payload"]["stage_cap"] == 200  # stage 1 default cap
