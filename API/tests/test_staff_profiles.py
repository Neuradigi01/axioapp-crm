"""HTTP coverage for /api/v1/staff (list, profile upsert, performance).

Profile fields are optional in the joined list, so a freshly-seeded
admin shows up in `GET /staff` immediately even before HR fills a
profile. `PUT /staff/{id}` then upserts the row, and a second PUT
replaces values rather than erroring.
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
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
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
async def test_list_staff_includes_user_without_profile(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get("/api/v1/staff", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    by_email = {r["email"]: r for r in rows}
    me = by_email[user.email]
    assert me["full_name"] == user.full_name
    assert me["commission_rate"] is None
    assert me["employment_status"] is None
    assert me["joined_at"] is None


@pytest.mark.asyncio
async def test_put_profile_creates_then_replaces(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.read", "staff.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.put(
        f"/api/v1/staff/{user.id}",
        json={
            "commission_rate": "5.00",
            "monthly_target": "100000",
            "rating": "4.5",
            "employment_status": "active",
        },
        headers=headers,
    )
    assert create.status_code == 200, create.text
    assert create.json()["commission_rate"] == "5.00"
    assert create.json()["monthly_target"] == "100000.00"
    assert create.json()["rating"] == "4.5"

    # PUT again — replaces, no 409.
    replace = await layered_client.put(
        f"/api/v1/staff/{user.id}",
        json={
            "commission_rate": "7.50",
            "monthly_target": "200000",
            "rating": "5",
            "employment_status": "leave",
        },
        headers=headers,
    )
    assert replace.status_code == 200, replace.text
    assert replace.json()["commission_rate"] == "7.50"
    assert replace.json()["employment_status"] == "leave"

    # GET /staff now shows the merged row.
    listed = await layered_client.get("/api/v1/staff", headers=headers)
    me = next(r for r in listed.json() if r["email"] == user.email)
    assert me["monthly_target"] == "200000.00"
    assert me["employment_status"] == "leave"


@pytest.mark.asyncio
async def test_put_profile_unknown_user_returns_404(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.put(
        f"/api/v1/staff/{uuid.uuid4()}",
        json={"commission_rate": "1", "monthly_target": "1", "rating": "1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_performance_returns_zero_when_no_leads_or_profile(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "staff.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.get(
        f"/api/v1/staff/{user.id}/performance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["leads_converted"] == 0
    assert body["leads_active"] == 0
    assert Decimal(body["sales"]) == Decimal("0")
    assert body["target_progress_pct"] is None


@pytest.mark.asyncio
async def test_staff_read_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/staff",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
