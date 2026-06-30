"""Tests for `POST /api/v1/subscriptions/change` (Step 8).

Coverage matches the spec's acceptance list:

  - Trial → Basic monthly (needs_payment with bundle preview).
  - Trial → Standard annual (needs_payment, annual bundle preview).
  - Standard → Basic (downgrade, scheduled at period_end).
  - Basic monthly → Basic annual (cycle-up upgrade → needs_payment).
  - Standard annual → Standard monthly (cycle-down → scheduled).
  - No-change request → outcome=no_change.
  - Seats below in-use → 400 seats_below_in_use.
  - Seats below bundle minimum → 400 seats_below_minimum.
  - Target plan = trial → 400 cannot_change_to_trial.
  - Cancelled sub → 400 cannot_change_cancelled.
  - Read-only sub → 200 needs_payment (recovery path).
  - Unknown to_plan → 404 unknown_plan.
  - Period-rollover applies next_* and clears the columns.
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
    """Step 12 wired `get_payment_provider` into `/subscriptions/change`.
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


async def _login(client, *, email: str, password: str, org_slug: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _insert_subscription(
    org_id: uuid.UUID,
    *,
    plan_code: str,
    status: str = "active",
    billing_cycle: str = "monthly",
    seats_purchased: int = 5,
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancelled_at: datetime | None = None,
    read_only_at: datetime | None = None,
    next_plan_code: str | None = None,
    next_billing_cycle: str | None = None,
    next_seats: int | None = None,
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
            next_plan_code=next_plan_code,
            next_billing_cycle=next_billing_cycle,
            next_seats=next_seats,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _add_extra_members(org_id: uuid.UUID, role_id: uuid.UUID, count: int) -> None:
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


async def _login_seeded(client, seeded_admin) -> str:
    return await _login(
        client,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
        org_slug=seeded_admin["org"].slug,
    )


async def _post_change(client, token: str, payload: dict):
    return await client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


# ---------------------------------------------------------------------------
# Upgrades — needs_payment branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_to_basic_monthly_needs_payment(layered_client, seeded_admin):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="trialing",
        seats_purchased=3,
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
        current_period_start=now,
        current_period_end=now + timedelta(days=14),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["checkout_url"] is None
    assert body["checkout_session_id"] is None
    assert body["preview"]["to_plan"] == "basic"
    assert body["preview"]["billing_cycle"] == "monthly"
    assert body["preview"]["seats"] == 5
    assert body["preview"]["amount_due_usd"] == 60  # basic monthly bundle


@pytest.mark.asyncio
async def test_trial_to_standard_annual_needs_payment(layered_client, seeded_admin):
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
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "standard", "billing_cycle": "annual", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["preview"]["amount_due_usd"] == 1392


# ---------------------------------------------------------------------------
# Downgrades — scheduled branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standard_to_basic_scheduled(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_subscription(
        org.id,
        plan_code="standard",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "scheduled"
    assert body["from_plan"] == "standard"
    assert body["to_plan"] == "basic"
    assert body["preview"]["amount_due_usd"] == 0

    # Verify the row was actually mutated.
    async with TestSession() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.id == sub_id))
        ).scalar_one()
        assert sub.next_plan_code == "basic"
        assert sub.next_billing_cycle == "monthly"
        assert sub.next_seats == 5


@pytest.mark.asyncio
async def test_basic_monthly_to_basic_annual_needs_payment(
    layered_client,
    seeded_admin,
):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "annual", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["preview"]["billing_cycle"] == "annual"
    assert body["preview"]["amount_due_usd"] == 576  # basic annual bundle


@pytest.mark.asyncio
async def test_standard_annual_to_standard_monthly_scheduled(
    layered_client,
    seeded_admin,
):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="standard",
        status="active",
        billing_cycle="annual",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "standard", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "scheduled"


# ---------------------------------------------------------------------------
# Idempotent no-change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_change_when_request_matches_current(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"outcome": "no_change"}


# ---------------------------------------------------------------------------
# Validation 4xx paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seats_below_in_use_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )
    # seeded_admin gives 1 active member; 3 more makes 4 active.
    await _add_extra_members(org.id, role.id, count=3)

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 2},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "seats_below_in_use"
    assert body["in_use"] == 4
    assert body["min_allowed"] == 5  # max(in_use=4, bundle_min=5)


@pytest.mark.asyncio
async def test_seats_below_bundle_minimum_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 3},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "seats_below_minimum"
    assert body["min_allowed"] == 5


@pytest.mark.asyncio
async def test_cannot_change_to_trial(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "trial", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "cannot_change_to_trial"


@pytest.mark.asyncio
async def test_cancelled_sub_cannot_change(layered_client, seeded_admin):
    """Cancelled subs are history — `get_active_subscription` filters
    them out, so the endpoint surfaces "no active sub" (400) rather
    than 404. Either way, the user cannot use this path; they need a
    fresh signup."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="cancelled",
        cancelled_at=now - timedelta(days=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "standard", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] in (
        "no_active_subscription",
        "cannot_change_cancelled",
    )


@pytest.mark.asyncio
async def test_read_only_can_change_recovery_path(layered_client, seeded_admin):
    """A trial that expired into read_only must be able to upgrade —
    that is the entire point of the "trial ended, choose a plan" banner.
    """
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        seats_purchased=3,
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        current_period_start=now - timedelta(days=15),
        current_period_end=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "needs_payment"


@pytest.mark.asyncio
async def test_unknown_to_plan_404(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_change(
        layered_client,
        token,
        {"to_plan": "xyz", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "unknown_plan"


# ---------------------------------------------------------------------------
# Period-rollover applies next_*
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_rollover_applies_scheduled_change(test_db):
    """Seed a sub past `current_period_end` with `next_plan_code` set;
    run the lifecycle scan; assert the live columns flipped and the
    `next_*` parking lot cleared.

    Uses `test_db` (the raw async session) instead of `layered_client`
    because no HTTP roundtrip is involved — this is a pure lifecycle
    test.
    """
    org = Organization(
        id=uuid.uuid4(),
        name="LC Co",
        slug=f"lc-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.flush()

    now = datetime.now(tz=UTC)
    sub = Subscription(
        org_id=org.id,
        plan_code="standard",
        status="active",
        billing_cycle="monthly",
        seats_purchased=5,
        current_period_start=now - timedelta(days=30),
        current_period_end=now - timedelta(hours=1),
        next_plan_code="basic",
        next_billing_cycle="monthly",
        next_seats=5,
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
    assert fresh.plan_code == "basic"
    assert fresh.billing_cycle == "monthly"
    assert fresh.seats_purchased == 5
    assert fresh.next_plan_code is None
    assert fresh.next_billing_cycle is None
    assert fresh.next_seats is None
    # Period advanced.
    assert fresh.current_period_end > now
