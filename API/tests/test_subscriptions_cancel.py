"""Tests for `POST /api/v1/subscriptions/cancel` (Step 10).

Covers:

  - Active subscription is flipped to `cancelled` with `cancelled_at`
    set and `already_cancelled=false`.
  - Cancel is idempotent — a second call returns
    `already_cancelled=true` with the original `cancelled_at`, and
    the audit log gets exactly one row.
  - After cancel, write endpoints get 402 via the middleware (the
    cancel endpoint itself remains writable, since it is on the
    allow-list).
  - An audit row with action `subscription.cancelled` is persisted.

The Step 19 RBAC test ("Non-owner cannot cancel: 403") is OWNED by
Step 19's test file — it requires the `billing.manage` permission key
that does not exist until then. Including it here would require
mocking out the permission system, which would be a brittle
workaround.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.app.core.audit.models import AuditLog
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


async def _insert_active_basic(org_id) -> uuid.UUID:
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
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


async def _post_cancel(client, token):
    return await client.post(
        "/api/v1/subscriptions/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_subscription_is_cancelled(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_active_basic(org.id)

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _post_cancel(layered_client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["already_cancelled"] is False
    assert body["cancelled_at"] is not None

    # Verify the row.
    async with TestSession() as session:
        fresh = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub_id)
            )
        ).scalar_one()
        assert fresh.status == "cancelled"
        assert fresh.cancelled_at is not None


# ---------------------------------------------------------------------------
# Idempotent — second call is a no-op, audit row not duplicated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_is_idempotent(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_active_basic(org.id)
    token = await _login_seeded(layered_client, seeded_admin)

    first = await _post_cancel(layered_client, token)
    second = await _post_cancel(layered_client, token)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["already_cancelled"] is False
    assert second.json()["already_cancelled"] is True
    # cancelled_at must not move on the no-op call.
    assert first.json()["cancelled_at"] == second.json()["cancelled_at"]

    async with TestSession() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "subscription.cancelled",
                    AuditLog.entity_id == sub_id,
                )
            )
        ).scalars().all()
    # Exactly one row — the second cancel must short-circuit before
    # the audit call. (The audit log is best-effort, so a `>= 1`
    # assertion would mask a duplicate-audit bug. We want exactly one.)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Cancel blocks subsequent writes via middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_then_writes_get_402(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_active_basic(org.id)
    token = await _login_seeded(layered_client, seeded_admin)

    resp_cancel = await _post_cancel(layered_client, token)
    assert resp_cancel.status_code == 200, resp_cancel.text

    resp_write = await layered_client.post(
        "/api/v1/contacts",
        headers={"Authorization": f"Bearer {token}"},
        json={"first_name": "X", "last_name": "Y"},
    )
    assert resp_write.status_code == 402, resp_write.text
    assert resp_write.json()["reason"] == "cancelled"


# ---------------------------------------------------------------------------
# Audit row written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_writes_audit_row(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    sub_id = await _insert_active_basic(org.id)
    token = await _login_seeded(layered_client, seeded_admin)

    resp = await _post_cancel(layered_client, token)
    assert resp.status_code == 200, resp.text

    async with TestSession() as session:
        row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "subscription.cancelled",
                    AuditLog.entity_id == sub_id,
                )
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.after is not None
    assert row.after.get("status") == "cancelled"
