"""HTTP coverage for /api/v1/staff-portal — picker list + PIN login.

The PIN is the last 4 digits of `users.phone`. The picker is gated to
users whose `staff_profile.employment_status='active'` — without a
profile, the user can't appear on the tablet picker (HR hasn't set
them up).
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.staff.models import EmploymentStatus, StaffProfile
from src.app.core.staff_portal.service import reset_rate_limit


@pytest.fixture(autouse=True)
def _reset_staff_rate_limit():
    reset_rate_limit()
    yield
    reset_rate_limit()


async def _setup_active_staff(
    user_id: uuid.UUID, org_id: uuid.UUID, *, phone: str = "9876543210"
) -> None:
    """Add a phone + active staff_profile so PIN login becomes possible."""
    from sqlalchemy import update

    from src.app.core.users.models import User
    from tests.conftest import TestSession

    async with TestSession() as session:
        await session.execute(update(User).where(User.id == user_id).values(phone=phone))
        session.add(
            StaffProfile(
                org_id=org_id,
                user_id=user_id,
                employment_status=EmploymentStatus.active,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_pickable_users_excludes_users_without_profile(layered_client, seeded_admin):
    org = seeded_admin["org"]
    resp = await layered_client.get(f"/api/v1/staff-portal/users?org_slug={org.slug}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.asyncio
async def test_pickable_users_returns_active_only(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _setup_active_staff(user.id, org.id)

    resp = await layered_client.get(f"/api/v1/staff-portal/users?org_slug={org.slug}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == str(user.id)
    assert rows[0]["full_name"] == user.full_name
    # PII filter — only id + full_name + avatar.
    assert set(rows[0].keys()) == {"id", "full_name", "avatar"}


@pytest.mark.asyncio
async def test_login_happy_path(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _setup_active_staff(user.id, org.id, phone="9876543210")

    resp = await layered_client.post(
        "/api/v1/staff-portal/auth/login",
        json={
            "org_slug": org.slug,
            "user_id": str(user.id),
            "pin": "3210",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "staff_token" in body and len(body["staff_token"]) > 50
    assert body["user_id"] == str(user.id)
    assert body["org_id"] == str(org.id)


@pytest.mark.asyncio
async def test_login_wrong_pin_returns_401(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _setup_active_staff(user.id, org.id, phone="9876543210")

    resp = await layered_client.post(
        "/api/v1/staff-portal/auth/login",
        json={
            "org_slug": org.slug,
            "user_id": str(user.id),
            "pin": "0000",
        },
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_inactive_profile_returns_401(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    from sqlalchemy import update

    from src.app.core.users.models import User
    from tests.conftest import TestSession

    async with TestSession() as session:
        await session.execute(update(User).where(User.id == user.id).values(phone="9876543210"))
        session.add(
            StaffProfile(
                org_id=org.id,
                user_id=user.id,
                employment_status=EmploymentStatus.leave,
            )
        )
        await session.commit()

    resp = await layered_client.post(
        "/api/v1/staff-portal/auth/login",
        json={
            "org_slug": org.slug,
            "user_id": str(user.id),
            "pin": "3210",
        },
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_unknown_org_returns_404(layered_client, seeded_admin):
    user = seeded_admin["user"]
    resp = await layered_client.post(
        "/api/v1/staff-portal/auth/login",
        json={
            "org_slug": "does-not-exist",
            "user_id": str(user.id),
            "pin": "1234",
        },
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_login_rate_limited_after_five_failures(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _setup_active_staff(user.id, org.id, phone="9876543210")

    # 5 wrong attempts → all 401 (the 5th records, the limiter blocks
    # the *next* one).
    for _ in range(5):
        bad = await layered_client.post(
            "/api/v1/staff-portal/auth/login",
            json={
                "org_slug": org.slug,
                "user_id": str(user.id),
                "pin": "0000",
            },
        )
        assert bad.status_code == 401, bad.text

    # 6th attempt is blocked even though the PIN is correct — the
    # window hasn't elapsed yet.
    blocked = await layered_client.post(
        "/api/v1/staff-portal/auth/login",
        json={
            "org_slug": org.slug,
            "user_id": str(user.id),
            "pin": "3210",
        },
    )
    assert blocked.status_code == 429, blocked.text


@pytest.mark.asyncio
async def test_admin_jwt_cannot_authenticate_staff_endpoints(layered_client, seeded_admin):
    """An admin JWT (scope='admin') must never satisfy `get_current_staff`.

    Smoke-tests the scope separation without hitting any
    `get_current_staff`-gated endpoint directly (we don't have one
    public yet — staff portal endpoints in this step are all
    unauthenticated). We exercise the dependency in unit form.
    """
    from fastapi import HTTPException

    from src.app.core.auth.dependencies import get_current_staff
    from src.app.shared.context import RequestContext, reset_context, set_context

    # Simulate the middleware after decoding an ADMIN token.
    token = set_context(
        RequestContext(
            org_id=seeded_admin["org"].id,
            user_id=seeded_admin["user"].id,
            token_id=uuid.uuid4(),
            scope="admin",
        )
    )
    try:
        from tests.conftest import TestSession

        async with TestSession() as session:
            with pytest.raises(HTTPException) as excinfo:
                await get_current_staff(db=session)
            assert excinfo.value.status_code == 401
    finally:
        reset_context(token)
