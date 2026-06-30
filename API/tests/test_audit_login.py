"""Audit-log coverage for the login flow."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.app.core.audit.models import AuditLog


async def _fetch_audit_rows(action: str) -> list[AuditLog]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_successful_login_writes_audit_row(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": seeded_admin["password"], "org_slug": org.slug},
    )
    assert resp.status_code == 200, resp.text

    rows = await _fetch_audit_rows("auth.login.success")
    assert len(rows) == 1
    row = rows[0]
    assert row.org_id == org.id
    assert row.user_id == user.id
    assert row.after is not None and "token_id" in row.after


@pytest.mark.asyncio
async def test_failed_login_writes_audit_row_with_null_user(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password", "org_slug": org.slug},
    )
    assert resp.status_code == 401

    rows = await _fetch_audit_rows("auth.login.failure")
    assert len(rows) == 1
    row = rows[0]
    assert row.org_id == org.id
    assert row.user_id is None
    assert row.before is not None and row.before.get("email") == user.email


@pytest.mark.asyncio
async def test_failed_login_unknown_email_writes_audit_row(layered_client, seeded_admin):
    org = seeded_admin["org"]

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@demo.local", "password": "x", "org_slug": org.slug},
    )
    assert resp.status_code == 401

    rows = await _fetch_audit_rows("auth.login.failure")
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].org_id == org.id


@pytest.mark.asyncio
async def test_failed_login_unknown_org_writes_no_audit(layered_client, seeded_admin):
    """Without a known tenant there's nowhere to attach the row — skipped by design."""
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_admin["user"].email,
            "password": "Admin@123",
            "org_slug": "no-such-org",
        },
    )
    assert resp.status_code == 401

    rows = await _fetch_audit_rows("auth.login.failure")
    assert rows == []
