"""Integration tests for `GET /api/v1/modules`."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.module_registry import discover_modules, registry
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.settings.module import MODULE as SETTINGS_MODULE


async def _grant(role_id: uuid.UUID, key: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        perm = await register_permission(session, key=key, module=key.split(".", 1)[0])
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


@pytest.fixture(autouse=True)
def _populate_registry():
    """Discovery is normally driven by app startup; in tests we run it
    explicitly so each test starts with the production module set."""
    registry.clear()
    discover_modules()
    yield
    registry.clear()


@pytest.mark.asyncio
async def test_user_with_permission_sees_settings(layered_client, seeded_admin):
    await _grant(seeded_admin["role"].id, "settings.read")

    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get("/api/v1/modules", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()}
    assert SETTINGS_MODULE.id in ids


@pytest.mark.asyncio
async def test_user_without_permission_does_not_see_settings(layered_client, seeded_admin):
    # Intentionally do NOT grant settings.read / settings.write.
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get("/api/v1/modules", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()}
    assert SETTINGS_MODULE.id not in ids


@pytest.mark.asyncio
async def test_modules_endpoint_requires_auth(layered_client):
    resp = await layered_client.get("/api/v1/modules")
    assert resp.status_code == 401
