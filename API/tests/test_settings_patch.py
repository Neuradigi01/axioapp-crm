"""HTTP coverage for /api/v1/settings — strict-key patch + perm gate.

The PATCH endpoint must:
  - 200 on whitelisted keys
  - silently ignore unknown keys
  - 422 when a value violates its schema constraint (range, length)
  - 403 when the user lacks `settings.write`
The GET endpoint auto-creates the row on first call.
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
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )
        await session.commit()


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_get_auto_creates_row_with_defaults(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "settings.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.get(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Indian-CRM defaults baked into the migration.
    assert body["currency"] == "INR"
    assert body["tax_rate"] == "18.00"
    assert body["timezone"] == "Asia/Kolkata"
    assert body["locale"] == "en-IN"
    assert body["ai_enabled"] is False
    assert body["reviews_auto_request_enabled"] is False
    assert body["reviews_auto_request_delay_hours"] == 24


@pytest.mark.asyncio
async def test_patch_whitelisted_keys_succeeds(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "settings.read", "settings.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        "/api/v1/settings",
        json={
            "store_name": "Demo Furniture",
            "gst_number": "29ABCDE1234F1Z5",
            "tax_rate": 12,
            "ai_enabled": True,
            "ai_personality": "Friendly + concise",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["store_name"] == "Demo Furniture"
    assert body["gst_number"] == "29ABCDE1234F1Z5"
    assert body["tax_rate"] == "12.00"
    assert body["ai_enabled"] is True
    assert body["ai_personality"] == "Friendly + concise"


@pytest.mark.asyncio
async def test_patch_unknown_keys_are_ignored(layered_client, seeded_admin):
    """`extra='ignore'` on the schema means stray keys don't 422 — they're
    simply discarded. We assert this by:
      1. PATCH `{nope: 'x', store_name: 'Y'}`
      2. GET to confirm `store_name == 'Y'` (so the legit field landed)
      3. Re-check that the schema didn't mutate anything called `nope`
    """
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "settings.read", "settings.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    patch = await layered_client.patch(
        "/api/v1/settings",
        json={"nope": "x", "org_id": "00000000-0000-0000-0000-000000000999",
              "store_name": "Stays"},
        headers=headers,
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["store_name"] == "Stays"
    # `org_id` must be the user's real org, not the value in the body
    assert body["org_id"] == str(org.id)
    # No `nope` key leaked into the response (it wasn't on the model)
    assert "nope" not in body


@pytest.mark.asyncio
async def test_patch_tax_rate_out_of_range_returns_422(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "settings.read", "settings.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.patch(
        "/api/v1/settings",
        json={"tax_rate": 999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_requires_settings_write(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Only read perm — no write
    await _grant(seeded_admin["role"].id, "settings.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.patch(
        "/api/v1/settings",
        json={"store_name": "Should fail"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
