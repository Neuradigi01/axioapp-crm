"""Tests for `GET /api/v1/subscriptions/current` (Step 7).

Coverage matches the spec's acceptance list:

  - Trial org returns a trial-shaped response with positive
    `days_remaining` and a `usage` row per meterable resource.
  - Basic org (post-upgrade) returns a non-trial response with
    `trial: null`.
  - `seats.in_use` reflects the live count of active org members.
  - `usage[].current` reflects the metered counter values.
  - Missing active subscription returns 404.
  - Cross-org isolation: the caller only ever sees their own org's row.
  - The admin role can read (the endpoint is auth-only — write paths
    are gated on Owner via Step 19).
  - `read_only` status surfaces as a boolean for the trial-ended banner.
  - Enterprise rows mark `is_unlimited=true` when the cap is -1.
  - `days_remaining` floors at 0 for trials that already expired.

All tests use `layered_client` + `seeded_admin` from conftest, plus a
direct `TestSession` insert for the Subscription row so each test
controls plan / status / dates without round-tripping through the
signup hook.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.usage_service import RESOURCE_PERIOD_KIND
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo, UserLogin


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
    plan_code: str = "trial",
    status: str = "trialing",
    billing_cycle: str = "monthly",
    seats_purchased: int = 3,
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    read_only_at: datetime | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> uuid.UUID:
    """Insert a Subscription row directly. Returns its id."""
    from tests.conftest import TestSession

    now = datetime.now(tz=timezone.utc)
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
            read_only_at=read_only_at,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _add_extra_members(
    org_id: uuid.UUID, role_id: uuid.UUID, count: int
) -> None:
    """Add `count` extra active members to the org.

    The members get unique login handles + emails; they need rows in
    `tbl_user_login` + `tbl_user_info` + `tbl_organization_members` so
    the count_active_members query sees them.
    """
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


def _trial_window(days: int = 14) -> tuple[datetime, datetime]:
    now = datetime.now(tz=timezone.utc)
    return now, now + timedelta(days=days)


# ---------------------------------------------------------------------------
# Trial org happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_org_returns_trial_response(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    started, ends = _trial_window(14)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="trialing",
        seats_purchased=3,
        trial_started_at=started,
        trial_ends_at=ends,
        current_period_start=started,
        current_period_end=ends,
    )

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["plan"]["code"] == "trial"
    assert body["status"] == "trialing"
    assert body["billing_cycle"] == "monthly"

    trial = body["trial"]
    assert trial is not None
    assert 1 <= trial["days_remaining"] <= 14

    assert body["period"]["renews_at"] == body["period"]["end"]
    assert body["seats"]["purchased"] == 3
    assert body["seats"]["in_use"] == 1  # only the seeded admin
    assert body["read_only"] is False
    assert body["archived"] is False
    assert body["cancelled"] is False
    assert body["stripe_customer_id"] is None
    assert body["stripe_subscription_id"] is None

    # One row per meterable resource — feature-gate caps (pipelines,
    # branches, etc.) are NOT in this snapshot by design.
    assert len(body["usage"]) == len(RESOURCE_PERIOD_KIND)
    resources = {row["resource"] for row in body["usage"]}
    assert resources == set(RESOURCE_PERIOD_KIND.keys())


# ---------------------------------------------------------------------------
# Paid plan path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_org_returns_non_trial_response(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        seats_purchased=5,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["plan"]["code"] == "basic"
    assert body["plan"]["included_seats"] == 5
    assert body["status"] == "active"
    assert body["trial"] is None
    assert body["seats"]["purchased"] == 5
    assert body["seats"]["included"] == 5


# ---------------------------------------------------------------------------
# seats.in_use reflects active members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seats_in_use_reflects_active_members(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    role = seeded_admin["role"]

    await _insert_subscription(org.id, plan_code="basic", status="active")
    # seeded_admin gives 1 active member; add 3 more so the total is 4.
    await _add_extra_members(org.id, role.id, count=3)

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["seats"]["in_use"] == 4


# ---------------------------------------------------------------------------
# Usage reflects counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_reflects_counters(layered_client, seeded_admin):
    from tests.conftest import TestSession
    from src.app.core.subscriptions import usage_service

    org = seeded_admin["org"]
    user = seeded_admin["user"]

    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id,
        plan_code="basic",
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    # Go through the real write path — `increment` resolves the right
    # period bucket for the `contacts` lifetime resource off the active
    # subscription, so the counter row lines up with what `snapshot`
    # later reads.
    async with TestSession() as session:
        await usage_service.increment(session, org.id, "contacts", delta=47)
        await session.commit()

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = {row["resource"]: row for row in resp.json()["usage"]}
    assert rows["contacts"]["current"] == 47


# ---------------------------------------------------------------------------
# 404 when no active subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_active_subscription_returns_404(layered_client, seeded_admin):
    """seeded_admin yields no subscription on its own; the endpoint 404s."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text
    assert "No active subscription" in resp.text


# ---------------------------------------------------------------------------
# Cross-org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_isolation(layered_client, seeded_admin):
    """User in org A only sees org A's subscription, not org B's."""
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]

    # Build a second org B with its own subscription (different plan).
    org_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_b_id, name="Other Co", slug=f"other-{uuid.uuid4().hex[:6]}"
            )
        )
        await session.commit()

    sub_a_id = await _insert_subscription(org_a.id, plan_code="basic", status="active")
    sub_b_id = await _insert_subscription(
        org_b_id, plan_code="standard", status="active"
    )
    assert sub_a_id != sub_b_id

    token = await _login(
        layered_client,
        email=user_a.email,
        password=seeded_admin["password"],
        org_slug=org_a.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(sub_a_id)
    assert body["plan"]["code"] == "basic"


# ---------------------------------------------------------------------------
# Admin role can read (no RBAC gate on read)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_role_can_read(layered_client, seeded_admin):
    """The seeded admin role has no `subscriptions.*` permissions yet
    (Step 19 introduces them). The read endpoint is intentionally
    permission-free — visible to any authenticated org member — so the
    call must still return 200."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _insert_subscription(org.id, plan_code="basic", status="active")

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# read_only status surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_status_surfaces_flag(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        current_period_start=now - timedelta(days=15),
        current_period_end=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "read_only"
    assert body["read_only"] is True
    assert body["archived"] is False
    assert body["cancelled"] is False


# ---------------------------------------------------------------------------
# is_unlimited for Enterprise caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enterprise_unlimited_rows_flagged(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _insert_subscription(
        org.id, plan_code="enterprise", status="active", billing_cycle="annual"
    )

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    rows = {row["resource"]: row for row in resp.json()["usage"]}
    # Enterprise sets every cap to -1; any meterable row must be flagged.
    assert rows["contacts"]["cap"] == -1
    assert rows["contacts"]["is_unlimited"] is True
    assert rows["automation_runs_per_month"]["is_unlimited"] is True


# ---------------------------------------------------------------------------
# days_remaining floors at 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_days_remaining_floors_at_zero(layered_client, seeded_admin):
    """A trial whose `trial_ends_at` is in the past must surface 0, not
    a negative integer. The subscription stays `trialing` here because
    the lifecycle task hasn't yet transitioned it to `read_only` — the
    endpoint must still render safely."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="trialing",
        trial_started_at=now - timedelta(days=20),
        trial_ends_at=now - timedelta(days=3),
        current_period_start=now - timedelta(days=20),
        current_period_end=now - timedelta(days=3),
    )

    token = await _login(
        layered_client,
        email=user.email,
        password=seeded_admin["password"],
        org_slug=org.slug,
    )
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["trial"]["days_remaining"] == 0
