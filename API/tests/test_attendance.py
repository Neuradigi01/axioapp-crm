"""HTTP coverage for /api/v1/staff/{id}/clock-in,clock-out,attendance.

The "at most one open session per user" invariant is enforced
service-side (not a DB constraint) so the test verifies it through
the public 409 contract.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_clock_in_then_clock_out_records_hours(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.read", "attendance.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    open_ = await layered_client.post(
        f"/api/v1/staff/{user.id}/clock-in",
        json={"notes": "morning shift"},
        headers=headers,
    )
    assert open_.status_code == 201, open_.text
    body = open_.json()
    assert body["clock_out_at"] is None
    assert body["hours"] is None
    assert body["notes"] == "morning shift"

    closed = await layered_client.post(
        f"/api/v1/staff/{user.id}/clock-out",
        json={"notes": "lunch"},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    closed_body = closed.json()
    assert closed_body["clock_out_at"] is not None
    # Generated `hours` should now be a non-negative decimal.
    assert closed_body["hours"] is not None
    assert Decimal(closed_body["hours"]) >= 0
    # Notes were appended.
    assert "morning shift" in closed_body["notes"]
    assert "lunch" in closed_body["notes"]


@pytest.mark.asyncio
async def test_second_clock_in_while_open_returns_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "attendance.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    first = await layered_client.post(f"/api/v1/staff/{user.id}/clock-in", json={}, headers=headers)
    assert first.status_code == 201, first.text

    second = await layered_client.post(
        f"/api/v1/staff/{user.id}/clock-in", json={}, headers=headers
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_clock_out_without_open_session_returns_404(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "attendance.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        f"/api/v1/staff/{user.id}/clock-out",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_attendance_history_listed_newest_first(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.read", "attendance.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Two complete sessions.
    for _ in range(2):
        in_ = await layered_client.post(
            f"/api/v1/staff/{user.id}/clock-in", json={}, headers=headers
        )
        assert in_.status_code == 201
        out_ = await layered_client.post(
            f"/api/v1/staff/{user.id}/clock-out", json={}, headers=headers
        )
        assert out_.status_code == 200

    resp = await layered_client.get(f"/api/v1/staff/{user.id}/attendance", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["clock_in_at"] >= rows[1]["clock_in_at"]


@pytest.mark.asyncio
async def test_clock_in_requires_attendance_write(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Only read perm granted — no attendance.write
    await _grant(seeded_admin["role"].id, "staff.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        f"/api/v1/staff/{user.id}/clock-in",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_self_clock_in_out_needs_no_attendance_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # No permissions granted — /me/* only needs a signed-in user.
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    before = await layered_client.get("/api/v1/staff/me/attendance/open", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json() is None

    opened = await layered_client.post("/api/v1/staff/me/clock-in", json={}, headers=headers)
    assert opened.status_code == 201, opened.text

    current = await layered_client.get("/api/v1/staff/me/attendance/open", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["id"] == opened.json()["id"]

    closed = await layered_client.post("/api/v1/staff/me/clock-out", json={}, headers=headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["clock_out_at"] is not None

    after = await layered_client.get("/api/v1/staff/me/attendance/open", headers=headers)
    assert after.json() is None


@pytest.mark.asyncio
async def test_self_clock_in_twice_returns_409_and_clock_out_when_closed_404(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    no_open = await layered_client.post("/api/v1/staff/me/clock-out", json={}, headers=headers)
    assert no_open.status_code == 404, no_open.text

    first = await layered_client.post("/api/v1/staff/me/clock-in", json={}, headers=headers)
    assert first.status_code == 201, first.text
    second = await layered_client.post("/api/v1/staff/me/clock-in", json={}, headers=headers)
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_self_clock_in_requires_authentication(layered_client):
    resp = await layered_client.post("/api/v1/staff/me/clock-in", json={})
    assert resp.status_code == 401
