"""Tests for the Step 12 checkout integration.

Covers three surfaces:

  - `POST /api/v1/subscriptions/checkout` direct upgrade flow.
  - `POST /api/v1/subscriptions/change` augmented with a Stripe URL
    when the outcome is `needs_payment`.
  - `POST /api/v1/subscriptions/seats` augmented likewise on a paid add.

The Stripe provider is overridden via FastAPI's `dependency_overrides`
so every test runs against an in-memory `MagicMock` that records calls
without hitting the real Stripe API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.payment_provider import CheckoutSessionResult


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
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
    stripe_customer_id: str | None = None,
) -> uuid.UUID:
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
            stripe_customer_id=stripe_customer_id,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


def _make_mock_provider(
    *,
    customer_id: str = "cus_mock_1",
    session_id: str = "cs_mock_1",
    checkout_url: str = "https://checkout.stripe.com/c/pay/cs_mock_1",
) -> MagicMock:
    """Mock provider that returns deterministic IDs.

    `create_customer` is an `AsyncMock` returning `customer_id`.
    `create_checkout_session` returns a real `CheckoutSessionResult`
    so the route's response-model coercion doesn't trip on type
    checks.
    """
    provider = MagicMock()
    provider.create_customer = AsyncMock(return_value=customer_id)
    provider.create_checkout_session = AsyncMock(
        return_value=CheckoutSessionResult(
            url=checkout_url,
            session_id=session_id,
            customer_id=customer_id,
        ),
    )
    return provider


@pytest.fixture
def mock_provider():
    return _make_mock_provider()


@pytest.fixture
def override_provider(layered_client, mock_provider):
    """Inject `mock_provider` for every route in this test.

    `layered_client` already imports the FastAPI app; we patch its
    dependency table and clean up afterwards.
    """
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: mock_provider
    try:
        # Clear the lru_cache so a real provider built earlier in the
        # process doesn't leak into the test.
        get_payment_provider.cache_clear()
        yield mock_provider
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()


# ---------------------------------------------------------------------------
# Direct checkout endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_checkout_creates_session_and_persists_id(
    layered_client, seeded_admin, override_provider,
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_subscription(
        org.id, plan_code="basic", status="active", seats_purchased=5,
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "standard",
            "billing_cycle": "monthly",
            "seats": 5,
            "success_url": "http://localhost:4200/user/settings/billing?upgraded=true",
            "cancel_url": "http://localhost:4200/user/settings/billing",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checkout_url"].startswith("https://checkout.stripe.com")
    assert body["session_id"] == "cs_mock_1"

    # Verify pending_checkout_session_id was persisted.
    async with TestSession() as session:
        fresh = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id)
            )
        ).scalar_one()
        assert fresh.pending_checkout_session_id == "cs_mock_1"


@pytest.mark.asyncio
async def test_direct_checkout_creates_customer_on_first_call(
    layered_client, seeded_admin, override_provider,
):
    """`stripe_customer_id` is null → provider.create_customer is
    invoked, and the row is updated with the returned id."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_subscription(
        org.id, plan_code="basic", seats_purchased=5,
        stripe_customer_id=None,
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "standard",
            "billing_cycle": "monthly",
            "seats": 5,
            "success_url": "http://localhost:4200/done",
            "cancel_url": "http://localhost:4200/back",
        },
    )
    assert resp.status_code == 200, resp.text
    override_provider.create_customer.assert_awaited_once()

    async with TestSession() as session:
        fresh = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id)
            )
        ).scalar_one()
        assert fresh.stripe_customer_id == "cus_mock_1"


@pytest.mark.asyncio
async def test_direct_checkout_reuses_existing_customer(
    layered_client, seeded_admin, override_provider,
):
    """Second checkout reuses the persisted `stripe_customer_id`;
    no new Customer is created."""
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id, plan_code="basic", seats_purchased=5,
        stripe_customer_id="cus_existing_42",
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "standard", "billing_cycle": "monthly", "seats": 5,
            "success_url": "http://localhost:4200/done",
            "cancel_url": "http://localhost:4200/back",
        },
    )
    assert resp.status_code == 200, resp.text
    override_provider.create_customer.assert_not_called()
    # The checkout session call still fired, with the existing customer.
    kwargs = override_provider.create_checkout_session.await_args.kwargs
    assert kwargs["customer_id"] == "cus_existing_42"


@pytest.mark.asyncio
async def test_direct_checkout_rejects_off_domain_success_url(
    layered_client, seeded_admin, override_provider,
):
    org = seeded_admin["org"]
    await _insert_subscription(org.id, plan_code="basic", seats_purchased=5)
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "standard", "billing_cycle": "monthly", "seats": 5,
            "success_url": "https://evil.example.com/win",
            "cancel_url": "http://localhost:4200/back",
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_redirect"
    override_provider.create_checkout_session.assert_not_called()


@pytest.mark.asyncio
async def test_direct_checkout_defaults_urls_when_omitted(
    layered_client, seeded_admin, override_provider,
):
    """Omitted URLs fall back to `/user/settings/billing` on the
    request's origin. We just assert the provider was called with
    non-empty success / cancel URLs containing the billing path."""
    org = seeded_admin["org"]
    await _insert_subscription(org.id, plan_code="basic", seats_purchased=5)
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "standard", "billing_cycle": "monthly", "seats": 5,
        },
    )
    assert resp.status_code == 200, resp.text
    kwargs = override_provider.create_checkout_session.await_args.kwargs
    assert "/user/settings/billing" in kwargs["success_url"]
    assert "/user/settings/billing" in kwargs["cancel_url"]


# ---------------------------------------------------------------------------
# change_plan integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_change_returns_real_url_when_provider_present(
    layered_client, seeded_admin, override_provider,
):
    """Trial → Standard via `POST /subscriptions/change` returns a
    needs_payment response with the mocked checkout URL filled."""
    org = seeded_admin["org"]
    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id, plan_code="trial", status="trialing",
        seats_purchased=3, trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "standard", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["checkout_url"].startswith("https://checkout.stripe.com")
    assert body["checkout_session_id"] == "cs_mock_1"


@pytest.mark.asyncio
async def test_downgrade_does_not_call_provider(
    layered_client, seeded_admin, override_provider,
):
    """Standard → Basic is a scheduled downgrade; no checkout needed."""
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id, plan_code="standard", status="active",
        seats_purchased=5,
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "scheduled"
    override_provider.create_checkout_session.assert_not_called()


@pytest.mark.asyncio
async def test_no_change_does_not_call_provider(
    layered_client, seeded_admin, override_provider,
):
    """Same plan + cycle + seats → no_change short-circuits."""
    org = seeded_admin["org"]
    await _insert_subscription(
        org.id, plan_code="basic", status="active",
        billing_cycle="monthly", seats_purchased=5,
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "no_change"
    override_provider.create_checkout_session.assert_not_called()


# ---------------------------------------------------------------------------
# change_seats integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_increase_returns_real_url_when_provider_present(
    layered_client, seeded_admin, override_provider,
):
    """Paid sub + seat increase → needs_payment with Stripe URL filled."""
    org = seeded_admin["org"]
    now = datetime.now(tz=timezone.utc)
    await _insert_subscription(
        org.id, plan_code="basic", status="active",
        billing_cycle="monthly", seats_purchased=5,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/seats",
        headers={"Authorization": f"Bearer {token}"},
        json={"total_seats": 8},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "needs_payment"
    assert body["checkout_url"].startswith("https://checkout.stripe.com")
    assert body["checkout_session_id"] == "cs_mock_1"


# ---------------------------------------------------------------------------
# Validation passes through from Steps 8 / 9
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_errors_propagate(
    layered_client, seeded_admin, override_provider,
):
    """seats below bundle min → 400 even on the checkout endpoint."""
    org = seeded_admin["org"]
    await _insert_subscription(org.id, plan_code="basic", seats_purchased=5)
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.post(
        "/api/v1/subscriptions/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "to_plan": "basic", "billing_cycle": "monthly", "seats": 3,
            "success_url": "http://localhost:4200/done",
            "cancel_url": "http://localhost:4200/back",
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "seats_below_minimum"
    override_provider.create_checkout_session.assert_not_called()
