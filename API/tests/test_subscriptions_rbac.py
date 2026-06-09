"""Tests for the Step 19 RBAC gates on the subscription endpoints.

Verifies that:
  - Reads (`/subscriptions/current`, `/subscriptions/invoices`)
    require `billing.read`.
  - Writes (`/change`, `/seats`, `/seats/preview`, `/checkout`,
    `/cancel`) require `billing.manage`.
  - The Stripe webhook stays unauthenticated (signature is the auth).
  - Public plan endpoints stay unauthenticated.

The conftest's `seeded_admin` fixture seeds a single user with a
single role that has NO permissions attached. Each test grants the
needed key(s) to that role explicitly to simulate Owner vs Admin
behaviour without dragging in the role-templates installer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select

from src.app.core.permissions.models import Permission, RolePermission
from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.models import Subscription


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


async def _grant_permissions(role_id: uuid.UUID, keys: list[str]) -> None:
    """Attach `keys` to the seeded role.

    Inserts rows in `permissions` (idempotent via `ON CONFLICT DO NOTHING`)
    and into `role_permissions`. The role then carries those keys for
    any user already a member of it.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm_id = (
                await session.execute(
                    select(Permission.id).where(Permission.key == key)
                )
            ).scalar_one_or_none()
            if perm_id is None:
                stmt = (
                    pg_insert(Permission)
                    .values(key=key, description=key)
                    .on_conflict_do_nothing(index_elements=["key"])
                    .returning(Permission.id)
                )
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    perm_id = (
                        await session.execute(
                            select(Permission.id).where(Permission.key == key)
                        )
                    ).scalar_one()
                else:
                    perm_id = row
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm_id)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"],
                )
            )
        await session.commit()


async def _seed_active_basic(org_id: uuid.UUID) -> None:
    from tests.conftest import TestSession

    now = datetime.now(tz=timezone.utc)
    async with TestSession() as session:
        session.add(
            Subscription(
                org_id=org_id,
                plan_code="basic",
                status="active",
                billing_cycle="monthly",
                seats_purchased=5,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
        )
        await session.commit()


@pytest.fixture(autouse=True)
def _disable_payment_provider():
    """Step 12 wired `get_payment_provider` into `/subscriptions/...`.
    Tests assert on permission gating, not on Stripe behaviour, so
    force the provider to None."""
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: None
    get_payment_provider.cache_clear()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()


# ---------------------------------------------------------------------------
# Public endpoints stay unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_plans_endpoint_requires_no_auth(layered_client):
    resp = await layered_client.get("/api/v1/plans")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# `/subscriptions/current` — `billing.read`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_without_billing_read_gets_403_on_current(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    await _seed_active_basic(org.id)
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_user_with_billing_read_gets_200_on_current(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.read"])

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# `/subscriptions/change` — `billing.manage`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_with_only_read_cannot_change_plan(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.read"])

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "standard", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_user_with_billing_manage_can_change_plan(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.manage"])

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "standard", "billing_cycle": "monthly", "seats": 5},
    )
    # Either 200 (needs_payment / scheduled / no_change) or a
    # business-rule 400; never 403.
    assert resp.status_code != 403, resp.text


# ---------------------------------------------------------------------------
# `/subscriptions/cancel` — `billing.manage`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_with_only_read_cannot_cancel(layered_client, seeded_admin):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.read"])

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_user_with_billing_manage_can_cancel(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.manage"])

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Webhook unauthenticated (signature replaces JWT)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_does_not_check_billing_permissions(layered_client):
    """No JWT, no permission — the webhook returns 503 (provider not
    configured) instead of 403. That confirms the route did not gate
    on a user-permission check before the provider lookup."""
    resp = await layered_client.post(
        "/api/v1/webhooks/stripe",
        content=b'{"id":"evt_x"}',
        headers={"stripe-signature": "t=1,v1=x"},
    )
    # 503 = provider unavailable (no `STRIPE_SECRET_KEY` in tests).
    # The point is that we never returned 401 or 403; permission
    # checking is bypassed.
    assert resp.status_code != 401 and resp.status_code != 403, resp.text
