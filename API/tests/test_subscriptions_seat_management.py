"""Tests for the Step 9 seat-management endpoints.

Covers `POST /api/v1/subscriptions/seats` (`change_seats`) and the
companion `GET /api/v1/subscriptions/seats/preview`. The test file
inherits the same `seeded_admin` + `layered_client` fixture pattern
the plan-change tests use; subscriptions are direct inserts so each
case controls plan / status / dates / seats.

Scenarios mirror the spec's acceptance list:

  - no_change when total matches current
  - trial cannot add seats
  - adding on Basic → needs_payment with positive proration
  - removing above floors → scheduled
  - removing below in-use → 400 seats_below_in_use
  - removing below bundle min → 400 seats_below_minimum
  - preview endpoint matches commit response shape
  - period-rollover applies next_seats
  - read-only can add seats (recovery path)
  - cancelled cannot change
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.lifecycle import scan_and_transition_due
from src.app.core.subscriptions.models import Subscription
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo
from src.models.user import UserLogin


@pytest.fixture(autouse=True)
def _disable_payment_provider():
    """Step 12 wired `get_payment_provider` into `/subscriptions/seats`.
    These tests assert `checkout_url=null`, so we force the override to
    return None and skip the Stripe round-trip.
    """
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: None
    get_payment_provider.cache_clear()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _login(client, *, email, password, org_slug) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _login_seeded(client, seeded_admin) -> str:
    return await _login(
        client,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
        org_slug=seeded_admin["org"].slug,
    )


async def _insert_subscription(
    org_id: uuid.UUID,
    *,
    plan_code: str,
    status: str = "active",
    billing_cycle: str = "monthly",
    seats_purchased: int = 5,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancelled_at: datetime | None = None,
    read_only_at: datetime | None = None,
    next_seats: int | None = None,
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    now = datetime.now(tz=UTC)
    cps = current_period_start or trial_started_at or now
    cpe = current_period_end or trial_ends_at or (now + timedelta(days=30))

    async with TestSession() as session:
        sub = Subscription(
            org_id=org_id,
            plan_code=plan_code,
            status=status,
            billing_cycle=billing_cycle,
            seats_purchased=seats_purchased,
            trial_started_at=trial_started_at,
            trial_ends_at=trial_ends_at,
            current_period_start=cps,
            current_period_end=cpe,
            cancelled_at=cancelled_at,
            read_only_at=read_only_at,
            next_seats=next_seats,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _add_extra_members(org_id, role_id, count):
    from tests.conftest import TestSession

    async with TestSession() as session:
        for _ in range(count):
            login = UserLogin(
                user_id=f"extra-{uuid.uuid4().hex[:8]}",
                password=hash_password("Extra@123"),
                is_active=True,
            )
            session.add(login)
            await session.flush()
            session.add(
                LegacyUserInfo(
                    member_id=login.id,
                    first_name="Extra",
                    last_name="Member",
                    email=f"extra-{uuid.uuid4().hex[:6]}@demo.local",
                    mobile_no="0000000000",
                )
            )
            session.add(
                OrganizationMember(
                    organization_id=org_id,
                    user_member_id=login.id,
                    role_id=role_id,
                    status="active",
                    is_active=True,
                    is_demo=False,
                )
            )
        await session.commit()


async def _post_seats(client, token, total_seats):
    return await client.post(
        "/api/v1/subscriptions/seats",
        headers={"Authorization": f"Bearer {token}"},
        json={"total_seats": total_seats},
    )


async def _get_seats_preview(client, token, total_seats):
    return await client.get(
        f"/api/v1/subscriptions/seats/preview?total_seats={total_seats}",
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# No-change short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_change_when_total_matches_current(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        seats_purchased=5,
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 5)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"outcome": "no_change"}


# ---------------------------------------------------------------------------
# Trial cannot add seats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_cannot_add_seats(layered_client, seeded_admin):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="trialing",
        seats_purchased=3,
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 4)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "trial_cannot_add_seats"


# ---------------------------------------------------------------------------
# Adding on Basic — needs_payment with positive proration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adding_seats_on_basic_needs_payment(layered_client, seeded_admin):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    # Fresh period start ⇒ proration fraction ≈ 1.0 ⇒ near-full extra
    # seat cost. Use start=now to keep the math predictable.
    await _insert_subscription(
        org.id,
        plan_code="basic",
        seats_purchased=5,
        billing_cycle="monthly",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 8)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["checkout_url"] is None
    preview = body["preview"]
    assert preview["from_seats"] == 5
    assert preview["to_seats"] == 8
    assert preview["delta"] == 3
    assert preview["outcome_if_committed"] == "needs_payment"
    # 3 extra seats * $12/mo * ~1.0 fraction = ~$36; allow slight
    # slippage because `now()` inside the service ticks past the fixture.
    assert 30 <= preview["amount_due_usd"] <= 36
    # Running monthly cost after change: $60 bundle + 3 extras × $12 = $96.
    assert preview["monthly_cost_after_change_usd"] == 96
    assert preview["annual_cost_after_change_usd"] is None


# ---------------------------------------------------------------------------
# Removing seats above floors → scheduled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removing_above_floors_scheduled(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    role = seeded_admin["role"]
    # 1 seeded admin + 5 extras = 6 in_use ; purchased = 8 ; bundle min = 5.
    sub_id = await _insert_subscription(
        org.id,
        plan_code="standard",
        seats_purchased=8,
        billing_cycle="monthly",
    )
    await _add_extra_members(org.id, role.id, count=5)

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 6)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "scheduled"
    assert body["from_seats"] == 8
    assert body["to_seats"] == 6
    assert body["refund_due_usd"] == 0

    async with TestSession() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.id == sub_id))
        ).scalar_one()
        assert sub.next_seats == 6
        assert sub.next_plan_code is None  # seat-only schedule
        assert sub.next_billing_cycle is None


# ---------------------------------------------------------------------------
# Validation 4xx — below in-use, below bundle min
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removing_below_in_use_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    # 1 + 5 = 6 in_use, purchased 8 ⇒ asking for 5 is below in-use.
    await _insert_subscription(
        org.id,
        plan_code="standard",
        seats_purchased=8,
    )
    await _add_extra_members(org.id, role.id, count=5)

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 5)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "seats_below_in_use"
    assert body["seats_in_use"] == 6
    assert body["min_allowed"] == 6  # max(in_use=6, bundle_min=5)


@pytest.mark.asyncio
async def test_removing_below_bundle_min_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    # 1 in_use, bundle min = 5; asking for 3 is below the bundle floor.
    await _insert_subscription(
        org.id,
        plan_code="basic",
        seats_purchased=5,
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 3)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "seats_below_minimum"
    assert body["min_allowed"] == 5


# ---------------------------------------------------------------------------
# Preview endpoint matches commit endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_matches_commit(layered_client, seeded_admin):
    """Preview shows the same proration math the commit response
    embeds. We compare `amount_due_usd` with a small tolerance because
    `datetime.now()` ticks between the two calls."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        seats_purchased=5,
        billing_cycle="monthly",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    token = await _login_seeded(layered_client, seeded_admin)

    preview_resp = await _get_seats_preview(layered_client, token, 7)
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert preview["delta"] == 2
    assert preview["outcome_if_committed"] == "needs_payment"

    commit_resp = await _post_seats(layered_client, token, 7)
    assert commit_resp.status_code == 200, commit_resp.text
    embedded = commit_resp.json()["preview"]
    assert embedded["delta"] == 2
    # Both amounts should be ~ 2 * $12 = $24 with proration ~ 1.0.
    assert abs(embedded["amount_due_usd"] - preview["amount_due_usd"]) <= 1


# ---------------------------------------------------------------------------
# Period-rollover applies next_seats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_rollover_applies_next_seats(test_db):
    """A seat-only schedule (next_seats set, next_plan_code/cycle NULL)
    must still flip live `seats_purchased` at the next boundary."""
    org = Organization(
        id=uuid.uuid4(),
        name="Seat Co",
        slug=f"seat-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.flush()

    now = datetime.now(tz=UTC)
    sub = Subscription(
        org_id=org.id,
        plan_code="standard",
        status="active",
        billing_cycle="monthly",
        seats_purchased=8,
        current_period_start=now - timedelta(days=30),
        current_period_end=now - timedelta(hours=1),
        next_seats=6,
    )
    test_db.add(sub)
    await test_db.commit()

    summary = await scan_and_transition_due(test_db)
    await test_db.commit()
    assert summary["scheduled_change_applied"] == 1

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.plan_code == "standard"  # unchanged
    assert fresh.billing_cycle == "monthly"  # unchanged
    assert fresh.seats_purchased == 6  # applied
    assert fresh.next_seats is None
    assert fresh.current_period_end > now


# ---------------------------------------------------------------------------
# Read-only sub can add seats (recovery path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_sub_can_add_seats(layered_client, seeded_admin):
    """A read-only org must be able to top up seats — it's part of the
    recovery flow that ends with an upgrade or reactivation."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="read_only",
        seats_purchased=5,
        current_period_start=now - timedelta(days=30),
        current_period_end=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 6)
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "needs_payment"


# ---------------------------------------------------------------------------
# Cancelled sub cannot change seats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_sub_cannot_change_seats(layered_client, seeded_admin):
    """Cancelled subs are excluded from `get_active_subscription`, so
    the endpoint reports `no_active_subscription`; either error code
    is acceptable as long as the request is refused with 400."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="cancelled",
        seats_purchased=5,
        cancelled_at=now - timedelta(days=1),
    )
    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_seats(layered_client, token, 6)
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] in (
        "no_active_subscription",
        "cannot_change_cancelled",
    )
