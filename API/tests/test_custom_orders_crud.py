"""HTTP-level CRUD coverage for /api/v1/custom-orders.

Covers:
  - create lands in the seeded initial stage (`measurement_scheduled`)
    and writes the first stage history row
  - list / get / patch / delete happy path
  - filter by `stage` query param
  - measurement append-only behaviour
  - 404 on nonexistent order
  - perm-gated writes (read works, write rejected without grant)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.packs.furniture.modules.custom_orders.models import (
    CustomOrderStageHistory,
)
from src.app.shared.context import RequestContext, reset_context, set_context


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
async def test_create_lands_in_initial_stage_and_logs_history(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/custom-orders",
        json={"title": "Walnut TV Unit", "total_amount": "42500.00"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pipeline_stage"] == "measurement_scheduled"
    assert body["title"] == "Walnut TV Unit"

    # History row recorded with from_stage NULL → measurement_scheduled.
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            rows = (
                (
                    await session.execute(
                        select(CustomOrderStageHistory).where(
                            CustomOrderStageHistory.order_id == uuid.UUID(body["id"])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].from_stage is None
            assert rows[0].to_stage == "measurement_scheduled"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_list_and_filter_by_stage(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for title in ("A", "B", "C"):
        resp = await layered_client.post(
            "/api/v1/custom-orders",
            json={"title": title},
            headers=headers,
        )
        assert resp.status_code == 201

    resp = await layered_client.get("/api/v1/custom-orders", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    resp = await layered_client.get(
        "/api/v1/custom-orders?stage=measurement_scheduled",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    resp = await layered_client.get("/api/v1/custom-orders?stage=design_phase", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/custom-orders",
        json={"title": "Original", "color": "Oak"},
        headers=headers,
    )
    order_id = resp.json()["id"]

    # GET
    g = await layered_client.get(f"/api/v1/custom-orders/{order_id}", headers=headers)
    assert g.status_code == 200
    assert g.json()["title"] == "Original"

    # PATCH
    p = await layered_client.patch(
        f"/api/v1/custom-orders/{order_id}",
        json={"title": "Updated", "advance_paid": "5000.00"},
        headers=headers,
    )
    assert p.status_code == 200
    assert p.json()["title"] == "Updated"
    assert p.json()["color"] == "Oak"  # untouched

    # DELETE
    d = await layered_client.delete(f"/api/v1/custom-orders/{order_id}", headers=headers)
    assert d.status_code == 204

    g2 = await layered_client.get(f"/api/v1/custom-orders/{order_id}", headers=headers)
    assert g2.status_code == 404


@pytest.mark.asyncio
async def test_measurements_append_only(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/custom-orders",
        json={"title": "Wardrobe"},
        headers=headers,
    )
    order_id = create.json()["id"]

    a = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/measurements",
        json={
            "item_label": "Wardrobe body",
            "length_cm": "220.00",
            "width_cm": "60.00",
            "height_cm": "240.00",
            "notes": "Wall-mounted",
        },
        headers=headers,
    )
    assert a.status_code == 201
    assert a.json()["item_label"] == "Wardrobe body"

    b = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/measurements",
        json={"item_label": "Drawer 1", "width_cm": "40.00"},
        headers=headers,
    )
    assert b.status_code == 201

    lst = await layered_client.get(
        f"/api/v1/custom-orders/{order_id}/measurements", headers=headers
    )
    assert lst.status_code == 200
    items = lst.json()
    assert len(items) == 2
    assert [m["item_label"] for m in items] == [
        "Wardrobe body",
        "Drawer 1",
    ]


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_orders.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(f"/api/v1/custom-orders/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    """A user with only `custom_orders.read` cannot POST."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_orders.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/custom-orders",
        json={"title": "Will fail"},
        headers=headers,
    )
    assert resp.status_code == 403
