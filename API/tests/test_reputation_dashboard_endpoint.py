"""Coverage for Step 7 of the email-reputation-warmup track —
Owner-only dashboard endpoint.

The endpoint's contract:

  * One synthetic ``platform_from`` row per org even when no events
    have landed (pristine card).
  * One row per verified ``own_domain`` (whether or not the reputation
    row exists yet).
  * Rates computed server-side against the 24h counters — client
    doesn't guard divide-by-zero.

The direct :func:`list_reputation_for_org` call is what the router
proxies; testing the service surface locks the shape without wiring
a whole HTTP client + JWT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.app.core.email.reputation.dashboard_service import list_reputation_for_org
from src.app.core.email.reputation.models import (
    ENVELOPE_TYPE_OWN_DOMAIN,
    ENVELOPE_TYPE_PLATFORM_FROM,
    REPUTATION_STATE_BLOCKED,
    REPUTATION_STATE_OK,
    OrganizationEmailReputation,
)
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_VERIFIED,
    OrganizationEmailDomain,
)
from src.app.core.tenants.models import Organization

pytestmark = pytest.mark.asyncio


async def _make_org(session, name: str = "Dash Org") -> Organization:
    org = Organization(id=uuid.uuid4(), name=name, slug=f"dash-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    return org


async def _make_verified_domain(session, *, org_id, name: str) -> OrganizationEmailDomain:
    dom = OrganizationEmailDomain(
        org_id=org_id,
        domain=name,
        mailgun_domain_id="mg-x",
        dns_records={},
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )
    session.add(dom)
    await session.flush()
    return dom


def _mock_counters(counts_by_key: dict[tuple[str, uuid.UUID | None], dict[str, int]]):
    """Return a patch that swaps ``counters.sum_last_24h`` for a fake
    keyed on (envelope, domain_id). Any (env, dom) not in the map
    returns 0 for every event."""

    async def _fake(*, org_id, envelope, domain_id, event):  # noqa: ARG001
        counts = counts_by_key.get((envelope, domain_id), {})
        return counts.get(event, 0)

    return patch(
        "src.app.core.email.reputation.dashboard_service.counters.sum_last_24h",
        side_effect=_fake,
    )


# ---------------------------------------------------------------------------
# 1. Pristine org — synthetic platform_from card, no domains
# ---------------------------------------------------------------------------


async def test_dashboard_returns_pristine_platform_from_row_when_no_events(test_db):
    """New org with no events yet → one row (platform_from) with
    zeros across the board, state = ok, warmup_stage = 0."""
    org = await _make_org(test_db)
    await test_db.commit()

    with _mock_counters({}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)

    assert len(rows) == 1
    r = rows[0]
    assert r.envelope_type == ENVELOPE_TYPE_PLATFORM_FROM
    assert r.domain_id is None
    assert r.warmup_stage == 0
    assert r.daily_sent == 0
    assert r.delivered_24h == 0
    assert r.complaint_rate == 0.0
    assert r.bounce_rate == 0.0
    assert r.reputation_state == REPUTATION_STATE_OK
    assert r.blocked_until is None


# ---------------------------------------------------------------------------
# 2. One row per envelope — platform_from + each verified own-domain
# ---------------------------------------------------------------------------


async def test_dashboard_returns_row_per_verified_own_domain(test_db):
    """Two verified own-domains + one platform_from → 3 rows total."""
    org = await _make_org(test_db)
    dom_a = await _make_verified_domain(
        test_db, org_id=org.id, name=f"a-{uuid.uuid4().hex[:6]}.example"
    )
    dom_b = await _make_verified_domain(
        test_db, org_id=org.id, name=f"b-{uuid.uuid4().hex[:6]}.example"
    )
    await test_db.commit()

    with _mock_counters({}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)

    envelopes = [r.envelope_type for r in rows]
    domain_ids = [r.domain_id for r in rows]
    assert envelopes == [
        ENVELOPE_TYPE_PLATFORM_FROM,
        ENVELOPE_TYPE_OWN_DOMAIN,
        ENVELOPE_TYPE_OWN_DOMAIN,
    ]
    assert dom_a.id in domain_ids
    assert dom_b.id in domain_ids
    # Own-domain rows carry the string label.
    own_rows = [r for r in rows if r.envelope_type == ENVELOPE_TYPE_OWN_DOMAIN]
    assert all(r.domain_string is not None for r in own_rows)


async def test_dashboard_skips_pending_domains(test_db):
    """A pending (not-yet-verified) own-domain does NOT appear in the
    dashboard — only verified ones do (reputation state is only
    meaningful post-verification)."""
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailDomain(
            org_id=org.id,
            domain=f"pending-{uuid.uuid4().hex[:6]}.example",
            mailgun_domain_id="mg-p",
            dns_records={},
            verification_status=VERIFICATION_STATUS_PENDING,
        )
    )
    await test_db.commit()

    with _mock_counters({}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)
    assert len(rows) == 1
    assert rows[0].envelope_type == ENVELOPE_TYPE_PLATFORM_FROM


# ---------------------------------------------------------------------------
# 3. Rates computed server-side
# ---------------------------------------------------------------------------


async def test_dashboard_computes_complaint_and_bounce_rates_from_counters(test_db):
    """Rates come from the 24h counters, not the DB mirror. Locks
    the contract that a Redis-side counter drift doesn't cause
    a divergence between the dashboard and the shed evaluator."""
    org = await _make_org(test_db)
    # Materialise a reputation row too, to prove rate math prefers
    # the counter values over the mirror columns.
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
            delivered_count_24h=0,  # deliberately stale
            complaint_count_24h=0,
        )
    )
    await test_db.commit()

    with _mock_counters(
        {
            (ENVELOPE_TYPE_PLATFORM_FROM, None): {
                "delivered": 1000,
                "complained": 3,
                "bounced": 20,
                "unsubscribed": 5,
            }
        }
    ):
        rows = await list_reputation_for_org(test_db, org_id=org.id)

    r = rows[0]
    assert r.delivered_24h == 1000
    assert r.complained_24h == 3
    assert r.bounced_24h == 20
    assert r.unsubscribed_24h == 5
    assert abs(r.complaint_rate - 0.003) < 1e-9
    assert abs(r.bounce_rate - 0.02) < 1e-9


async def test_dashboard_rate_zero_when_no_delivered(test_db):
    """Divide-by-zero guard — 0 delivered means the rate is 0, not
    NaN. Client can render the tile without a special case."""
    org = await _make_org(test_db)
    await test_db.commit()

    with _mock_counters({(ENVELOPE_TYPE_PLATFORM_FROM, None): {"complained": 5}}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)

    assert rows[0].delivered_24h == 0
    assert rows[0].complaint_rate == 0.0


# ---------------------------------------------------------------------------
# 4. State + warmup surfacing
# ---------------------------------------------------------------------------


async def test_dashboard_surfaces_blocked_state_and_blocked_until(test_db):
    org = await _make_org(test_db)
    blocked_at = datetime.now(UTC) + timedelta(hours=2)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
            warmup_stage=0,
            reputation_state=REPUTATION_STATE_BLOCKED,
            blocked_until=blocked_at,
        )
    )
    await test_db.commit()

    with _mock_counters({}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)

    r = rows[0]
    assert r.reputation_state == REPUTATION_STATE_BLOCKED
    assert r.blocked_until is not None
    # Timestamp comparison — treat within a second as equal.
    assert abs((r.blocked_until - blocked_at).total_seconds()) < 1


async def test_dashboard_stage_cap_matches_warmup_ladder(test_db):
    """Stage 3 → cap 5000 (default ladder). Locks the ladder in the
    response shape so the frontend's progress bar has a stable
    denominator."""
    org = await _make_org(test_db)
    test_db.add(
        OrganizationEmailReputation(
            org_id=org.id,
            envelope_type=ENVELOPE_TYPE_PLATFORM_FROM,
            domain_id=None,
            warmup_stage=3,
            daily_sent_count=100,
        )
    )
    await test_db.commit()

    with _mock_counters({}):
        rows = await list_reputation_for_org(test_db, org_id=org.id)
    r = rows[0]
    assert r.warmup_stage == 3
    assert r.stage_cap == 5000
    assert r.daily_cap == 5000
    # 100 / 5000 = 2%.
    assert abs(r.stage_progress_pct - 2.0) < 1e-6


async def test_dashboard_scoped_by_org_no_cross_leak(test_db):
    """Two orgs each with a reputation row + verified domain. Each
    call returns only the caller's rows — cross-org isolation."""
    org_a = await _make_org(test_db, "A")
    org_b = await _make_org(test_db, "B")
    dom_a = await _make_verified_domain(
        test_db, org_id=org_a.id, name=f"a-{uuid.uuid4().hex[:6]}.example"
    )
    dom_b = await _make_verified_domain(
        test_db, org_id=org_b.id, name=f"b-{uuid.uuid4().hex[:6]}.example"
    )
    await test_db.commit()

    with _mock_counters({}):
        rows_a = await list_reputation_for_org(test_db, org_id=org_a.id)
        rows_b = await list_reputation_for_org(test_db, org_id=org_b.id)

    domain_ids_a = {r.domain_id for r in rows_a if r.domain_id}
    domain_ids_b = {r.domain_id for r in rows_b if r.domain_id}
    assert dom_a.id in domain_ids_a
    assert dom_b.id in domain_ids_b
    assert dom_a.id not in domain_ids_b
    assert dom_b.id not in domain_ids_a
