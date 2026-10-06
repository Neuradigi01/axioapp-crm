"""Pack routers are tenant-gated by `require_pack`.

A user holding a pack's permission keys must still get 404 from that
pack's endpoints when their org is on a different pack — the leak this
guards against is a real-estate org reaching furniture Field Ops.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tenants.models import Organization


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


async def _set_template(org_id: uuid.UUID, template_id: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        await session.execute(
            update(Organization).where(Organization.id == org_id).values(template_id=template_id)
        )
        await session.commit()


async def _auth_headers(client, seeded: dict) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded["user"].email,
            "password": seeded["password"],
            "org_slug": seeded["org"].slug,
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("template_id", "path", "keys"),
    [
        ("real_estate", "/api/v1/field-visits", ("field_visits.read",)),
        ("base", "/api/v1/custom-orders", ("custom_orders.read",)),
        ("furniture", "/api/v1/property", ("property.read",)),
    ],
)
async def test_pack_endpoint_404s_for_other_pack(
    layered_client, seeded_admin, template_id, path, keys
):
    await _set_template(seeded_admin["org"].id, template_id)
    await _grant(seeded_admin["role"].id, *keys)
    headers = await _auth_headers(layered_client, seeded_admin)

    resp = await layered_client.get(path, headers=headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_pack_endpoint_open_for_own_pack(layered_client, seeded_admin):
    await _set_template(seeded_admin["org"].id, "furniture")
    await _grant(seeded_admin["role"].id, "field_visits.read")
    headers = await _auth_headers(layered_client, seeded_admin)

    resp = await layered_client.get("/api/v1/field-visits", headers=headers)
    assert resp.status_code == 200, resp.text
