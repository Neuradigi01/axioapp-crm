"""Tests for the Step 19 audit-event coverage on the billing surface.

Verifies that every billing state-change site writes an `audit_logs`
row with the expected action name and an `org_id` matching the
affected org. Payload-shape assertions are loose so future fields
land without test churn.

The bulk of the audit emission was done across Steps 6-13 as those
features landed; Step 19's contribution is `subscription.created` in
the signup hook, plus the safety net these tests provide that none of
the existing emits regressed silently.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.app.core.audit.models import AuditLog
from src.app.core.permissions.models import Permission, RolePermission
from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.lifecycle import scan_and_transition_due
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.signup_hook import create_trial_subscription
from src.app.core.subscriptions.webhooks.handlers.checkout_completed import (
    on_checkout_completed,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers — mirror the RBAC test file so tests are self-contained.
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


async def _seed_active_basic(
    org_id: uuid.UUID, stripe_subscription_id: str | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    now = datetime.now(tz=timezone.utc)
    async with TestSession() as session:
        sub = Subscription(
            org_id=org_id,
            plan_code="basic",
            status="active",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            stripe_subscription_id=stripe_subscription_id,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _read_audit_rows(action: str, org_id: uuid.UUID) -> list[AuditLog]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == action,
                    AuditLog.org_id == org_id,
                )
            )
        ).scalars().all()
    return list(rows)


@pytest.fixture(autouse=True)
def _disable_payment_provider():
    from src.app.main import app

    app.dependency_overrides[get_payment_provider] = lambda: None
    get_payment_provider.cache_clear()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_payment_provider, None)
        get_payment_provider.cache_clear()


# ---------------------------------------------------------------------------
# Signup hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_hook_emits_subscription_created(test_db):
    org = Organization(
        id=uuid.uuid4(),
        name="New Co",
        slug=f"new-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.commit()

    await create_trial_subscription(test_db, org_id=org.id)
    await test_db.commit()

    rows = await _read_audit_rows("subscription.created", org.id)
    assert len(rows) == 1
    after = rows[0].after or {}
    assert after.get("plan_code") == "trial"
    assert after.get("status") == "trialing"


# ---------------------------------------------------------------------------
# Plan change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_change_emits_change_scheduled_audit(
    layered_client, seeded_admin,
):
    org = seeded_admin["org"]
    role = seeded_admin["role"]
    await _seed_active_basic(org.id)
    await _grant_permissions(role.id, ["billing.manage"])

    # Insert a Standard sub so requesting Basic is a downgrade →
    # outcome=scheduled, which emits `subscription.change_scheduled`.
    from tests.conftest import TestSession

    async with TestSession() as session:
        existing = (
            await session.execute(
                select(Subscription).where(Subscription.org_id == org.id)
            )
        ).scalar_one()
        existing.plan_code = "standard"
        await session.commit()

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "scheduled"

    rows = await _read_audit_rows("subscription.change_scheduled", org.id)
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_emits_subscription_cancelled_audit(
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

    rows = await _read_audit_rows("subscription.cancelled", org.id)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Webhook → checkout completed → subscription.upgraded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_handler_emits_upgraded_audit(test_db):
    org = Organization(
        id=uuid.uuid4(),
        name="Webhook Co",
        slug=f"wh-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.commit()

    now = datetime.now(tz=timezone.utc)
    sub = Subscription(
        org_id=org.id,
        plan_code="trial",
        status="trialing",
        billing_cycle="monthly",
        seats_purchased=3,
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
        current_period_start=now,
        current_period_end=now + timedelta(days=14),
    )
    test_db.add(sub)
    await test_db.commit()
    await test_db.refresh(sub)

    event = {
        "id": "evt_x",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_x",
                "subscription": "sub_x",
                "customer": "cus_x",
                "metadata": {
                    "org_id": str(org.id),
                    "plan_code": "standard",
                    "billing_cycle": "monthly",
                    "seats": "5",
                },
            },
        },
    }
    await on_checkout_completed(test_db, event)
    await test_db.commit()

    rows = await _read_audit_rows("subscription.upgraded", org.id)
    assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Trial expiry → trial.expired audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trial_expiry_emits_trial_expired_audit(test_db):
    org = Organization(
        id=uuid.uuid4(),
        name="Expiry Co",
        slug=f"exp-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.flush()

    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=org.id,
            plan_code="trial",
            status="trialing",
            billing_cycle="monthly",
            seats_purchased=3,
            trial_started_at=now - timedelta(days=15),
            trial_ends_at=now - timedelta(hours=1),
            current_period_start=now - timedelta(days=15),
            current_period_end=now - timedelta(hours=1),
        )
    )
    await test_db.commit()

    summary = await scan_and_transition_due(test_db)
    await test_db.commit()
    assert summary["trialing_to_read_only"] == 1

    rows = await _read_audit_rows("trial.expired", org.id)
    assert len(rows) >= 1
