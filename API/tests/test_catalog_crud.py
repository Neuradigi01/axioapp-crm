"""HTTP coverage for /api/v1/catalog.

Covers: create / get / list / patch / delete, SKU uniqueness per org,
SKU normalization (case + whitespace), q + category filters, perm gates.
"""

from __future__ import annotations

import uuid

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
async def test_create_get_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read", "catalog.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Spec verification line: POST body={sku:"SOF001",name:"3-seater Sofa",price:25000,category:"Sofa"} → 201
    create = await layered_client.post(
        "/api/v1/catalog",
        json={
            "sku": "SOF001",
            "name": "3-seater Sofa",
            "price": 25000,
            "category": "Sofa",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["sku"] == "SOF001"
    assert body["name"] == "3-seater Sofa"
    assert body["currency"] == "INR"
    assert body["is_active"] is True
    item_id = body["id"]

    got = await layered_client.get(f"/api/v1/catalog/{item_id}", headers=headers)
    assert got.status_code == 200

    patch = await layered_client.patch(
        f"/api/v1/catalog/{item_id}",
        json={"price": "27500.00", "is_active": False},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["price"] == "27500.00"
    assert patch.json()["is_active"] is False

    delete = await layered_client.delete(f"/api/v1/catalog/{item_id}", headers=headers)
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_sku_normalized_to_upper_trimmed(layered_client, seeded_admin):
    """`sku` should be upper-cased and trimmed at the boundary."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read", "catalog.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/catalog",
        json={
            "sku": "  sof002 ",
            "name": "Lounger",
            "price": 18000,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["sku"] == "SOF002"


@pytest.mark.asyncio
async def test_duplicate_sku_per_org_returns_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read", "catalog.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"sku": "DUP001", "name": "Original", "price": 1000}
    first = await layered_client.post("/api/v1/catalog", json=payload, headers=headers)
    assert first.status_code == 201

    # Same SKU (and case-variant) under the same org → 409.
    for sku in ("DUP001", "dup001", "  Dup001 "):
        dup = await layered_client.post(
            "/api/v1/catalog",
            json={"sku": sku, "name": "Copy", "price": 9999},
            headers=headers,
        )
        assert dup.status_code == 409, (sku, dup.text)


@pytest.mark.asyncio
async def test_list_q_and_category_filters(layered_client, seeded_admin):
    """`q` ILIKEs name+sku; `category` is exact match."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read", "catalog.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for item in [
        {"sku": "SOF010", "name": "Premium Sofa", "price": 50000, "category": "Sofa"},
        {"sku": "TBL010", "name": "Coffee Table", "price": 8000, "category": "Table"},
        {"sku": "SOF011", "name": "Recliner", "price": 35000, "category": "Sofa"},
    ]:
        r = await layered_client.post("/api/v1/catalog", json=item, headers=headers)
        assert r.status_code == 201, r.text

    # Spec line: `GET /catalog?q=sofa` → returns it
    by_q = await layered_client.get("/api/v1/catalog?q=sofa", headers=headers)
    assert by_q.status_code == 200
    names = {i["name"] for i in by_q.json()["items"]}
    assert "Premium Sofa" in names
    # SKU starting with SOF also matches via OR
    assert "Recliner" in names

    by_cat = await layered_client.get("/api/v1/catalog?category=Table", headers=headers)
    names = {i["name"] for i in by_cat.json()["items"]}
    assert names == {"Coffee Table"}

    # Combo
    combo = await layered_client.get("/api/v1/catalog?q=Recliner&category=Sofa", headers=headers)
    assert combo.json()["total"] == 1


@pytest.mark.asyncio
async def test_active_only_filter(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read", "catalog.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    active = await layered_client.post(
        "/api/v1/catalog",
        json={"sku": "ACT001", "name": "Active item", "price": 100},
        headers=headers,
    )
    inactive = await layered_client.post(
        "/api/v1/catalog",
        json={
            "sku": "INACT001",
            "name": "Discontinued item",
            "price": 100,
            "is_active": False,
        },
        headers=headers,
    )
    assert active.status_code == 201 and inactive.status_code == 201

    all_list = await layered_client.get("/api/v1/catalog", headers=headers)
    skus_all = {i["sku"] for i in all_list.json()["items"]}
    assert "ACT001" in skus_all and "INACT001" in skus_all

    active_only = await layered_client.get("/api/v1/catalog?active_only=true", headers=headers)
    skus_active = {i["sku"] for i in active_only.json()["items"]}
    assert "ACT001" in skus_active and "INACT001" not in skus_active


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "catalog.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/catalog",
        json={"sku": "X", "name": "X", "price": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
