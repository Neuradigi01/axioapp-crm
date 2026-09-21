"""Coverage for Step 5 of the email-reputation-warmup track — send-
gate chain.

Direct-call tests against the four gate functions + the
``run_send_gate`` orchestrator. The refactor in ``send_email``
raises the resulting ``SendGateSkipped`` as an HTTP 429 with the
skip code embedded; that layer is thin so it isn't retested here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.app.core.email.reputation import gates
from src.app.core.email.reputation.exceptions import (
    SendGateSkipped,
    SkippedRateLimit,
    SkippedReputationBlock,
    SkippedSendingLimit,
)
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
    REPUTATION_STATE_OK,
    OrganizationEmailReputation,
)
from src.app.core.email.reputation.skip_codes import SendSkipCode
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


async def _make_org(session) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Gate Org",
        slug=f"gate-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_row(
    session,
    *,
    org_id: uuid.UUID,
    envelope: str = ENVELOPE_TYPE_PLATFORM_FROM,
    stage: int = 0,
    daily_sent: int = 0,
    state: str = REPUTATION_STATE_OK,
    blocked_until: datetime | None = None,
) -> OrganizationEmailReputation:
    row = OrganizationEmailReputation(
        org_id=org_id,
        envelope_type=envelope,
        domain_id=None,
        warmup_stage=stage,
        daily_sent_count=daily_sent,
        reputation_state=state,
        blocked_until=blocked_until,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# 1. Individual gate behaviour
# ---------------------------------------------------------------------------


async def test_check_reputation_blocked_raises(test_db):
    org = await _make_org(test_db)
    await _make_row(
        test_db,
        org_id=org.id,
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) + timedelta(hours=1),
    )
    await test_db.commit()

    with pytest.raises(SkippedReputationBlock):
        await gates.check_reputation(
            test_db,
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
        )


async def test_check_reputation_blocked_but_cooldown_elapsed_passes(test_db):
    """A row still marked ``blocked`` whose ``blocked_until`` has
    passed lets the send through — the hourly sweeper hasn't flipped
    state yet, but the cooldown expired."""
    org = await _make_org(test_db)
    await _make_row(
        test_db,
        org_id=org.id,
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) - timedelta(minutes=5),
    )
    await test_db.commit()

    # No exception.
    await gates.check_reputation(
        test_db,
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
    )


async def test_check_reputation_no_row_passes(test_db):
    """Brand-new envelope with no row = no block. First send is
    always allowed; row materialises on the events-webhook path."""
    org = await _make_org(test_db)
    await test_db.commit()

    await gates.check_reputation(
        test_db,
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
    )


async def test_check_ceiling_over_cap_raises(test_db):
    """Row at stage 0 (cap 50) with daily_sent_count = 50 raises."""
    org = await _make_org(test_db)
    await _make_row(test_db, org_id=org.id, stage=0, daily_sent=50)
    await test_db.commit()

    with pytest.raises(SkippedSendingLimit):
        await gates.check_ceiling(
            test_db,
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
        )


async def test_check_ceiling_under_cap_passes(test_db):
    org = await _make_org(test_db)
    await _make_row(test_db, org_id=org.id, stage=0, daily_sent=49)
    await test_db.commit()

    await gates.check_ceiling(
        test_db,
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
    )


async def test_check_wallet_no_op_when_credits_system_absent(test_db):
    """Default env has EMAIL_SEND_WALLET_ENABLED=false → wallet gate
    returns a zero-amount handle without raising."""
    org = await _make_org(test_db)
    await test_db.commit()

    debit = await gates.check_wallet(test_db, org_id=org.id)
    assert debit.org_id == org.id
    assert debit.amount == 0


async def test_check_rate_limit_over_hourly_raises(monkeypatch):
    org_id = uuid.uuid4()
    # Tighten the platform_from cap to 2/h so the third hit fails.
    monkeypatch.setenv("EMAIL_RATE_LIMIT_PLATFORM_FROM_PER_HOUR", "2")

    # First 2 admitted.
    for _ in range(2):
        await gates.check_rate_limit(org_id=org_id, envelope_type=ENVELOPE_TYPE_PLATFORM_FROM)
    # Third → skip.
    with pytest.raises(SkippedRateLimit):
        await gates.check_rate_limit(org_id=org_id, envelope_type=ENVELOPE_TYPE_PLATFORM_FROM)


# ---------------------------------------------------------------------------
# 2. Orchestrator ordering
# ---------------------------------------------------------------------------


async def test_gate_reputation_first_short_circuits_no_wallet_debit(test_db):
    """A blocked row raises SkippedReputationBlock BEFORE the wallet
    gate is reached. Locks the ordering — a subsequent wallet
    implementation would still see reputation_block first."""
    org = await _make_org(test_db)
    await _make_row(
        test_db,
        org_id=org.id,
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) + timedelta(hours=1),
    )
    await test_db.commit()

    with pytest.raises(SkippedReputationBlock):
        await gates.run_send_gate(
            test_db,
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
        )


async def test_gate_ceiling_second_short_circuits_no_rate_limit_hit(test_db):
    """Over-cap row raises SkippedSendingLimit before the rate gate.
    Prevents a hot loop from burning through rate budget while the
    ceiling was already tripped."""
    org = await _make_org(test_db)
    await _make_row(
        test_db,
        org_id=org.id,
        stage=0,
        daily_sent=100,  # way over stage-0 cap of 50
    )
    await test_db.commit()

    with pytest.raises(SkippedSendingLimit):
        await gates.run_send_gate(
            test_db,
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
        )


async def test_gate_bypass_flag_disables_chain(test_db, monkeypatch):
    """EMAIL_REPUTATION_GATES_ENABLED=false restores pre-Step-5
    behaviour — every gate short-circuits."""
    monkeypatch.setenv("EMAIL_REPUTATION_GATES_ENABLED", "false")
    org = await _make_org(test_db)
    # Blocked + over-cap — normally this would raise twice over.
    await _make_row(
        test_db,
        org_id=org.id,
        stage=0,
        daily_sent=100,
        state=REPUTATION_STATE_BLOCKED,
        blocked_until=datetime.now(UTC) + timedelta(hours=1),
    )
    await test_db.commit()

    debit = await gates.run_send_gate(
        test_db,
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
        domain_id=None,
    )
    assert debit.amount == 0


async def test_gate_non_reputation_envelope_short_circuits(test_db):
    """OAuth / SMTP envelope kinds don't participate in reputation —
    the gate short-circuits so we don't inadvertently block the
    non-Mailgun paths on a reputation lookup."""
    org = await _make_org(test_db)
    # No reputation row for "oauth_account" — proves the gate
    # didn't even try to look it up.
    debit = await gates.run_send_gate(
        test_db,
        org_id=org.id,
        envelope_type="oauth_account",
        domain_id=None,
    )
    assert debit.amount == 0


# ---------------------------------------------------------------------------
# 3. Skip-code enum contract
# ---------------------------------------------------------------------------


def test_skip_code_enum_values_are_stable():
    """The string values are stable — downstream log parsers key off
    them. Renaming would break dashboards."""
    assert SendSkipCode.REPUTATION_BLOCK.value == "SKIPPED_REPUTATION_BLOCK"
    assert SendSkipCode.SENDING_LIMIT.value == "SKIPPED_SENDING_LIMIT"
    assert SendSkipCode.WALLET_EMPTY.value == "SKIPPED_WALLET_EMPTY"
    assert SendSkipCode.RATE_LIMIT.value == "SKIPPED_RATE_LIMIT"


def test_skip_code_exceptions_carry_matching_code():
    """Every exception subclass carries its skip-code — the caller's
    ``except SendGateSkipped as exc: log(exc.code)`` doesn't need to
    introspect the class name."""
    assert SkippedReputationBlock().code == SendSkipCode.REPUTATION_BLOCK
    assert SkippedSendingLimit().code == SendSkipCode.SENDING_LIMIT
    assert SkippedRateLimit().code == SendSkipCode.RATE_LIMIT
    # Every SkippedX is a SendGateSkipped subclass.
    assert issubclass(SkippedReputationBlock, SendGateSkipped)
    assert issubclass(SkippedSendingLimit, SendGateSkipped)
    assert issubclass(SkippedRateLimit, SendGateSkipped)


async def test_gate_own_domain_uses_domain_id(test_db):
    """own_domain rows are keyed by (org, domain_id) — a gate for
    domain A must not read domain B's reputation."""
    from src.app.core.email_sender_setup.models import (
        VERIFICATION_STATUS_VERIFIED,
        OrganizationEmailDomain,
    )

    org = await _make_org(test_db)
    dom_a = OrganizationEmailDomain(
        org_id=org.id,
        domain=f"a-{uuid.uuid4().hex[:6]}.example",
        mailgun_domain_id="mg-a",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    dom_b = OrganizationEmailDomain(
        org_id=org.id,
        domain=f"b-{uuid.uuid4().hex[:6]}.example",
        mailgun_domain_id="mg-b",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    test_db.add_all([dom_a, dom_b])
    await test_db.flush()

    # A blocked, B ok.
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
            domain_id=dom_a.id,
            reputation_state=REPUTATION_STATE_BLOCKED,
            blocked_until=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await test_db.commit()

    # A: blocks. B: passes.
    with pytest.raises(SkippedReputationBlock):
        await gates.check_reputation(
            test_db,
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
            domain_id=dom_a.id,
        )
    await gates.check_reputation(
        test_db,
        org_id=org.id,
        envelope_type=ENVELOPE_TYPE_OWN_DOMAIN,
        domain_id=dom_b.id,
    )
