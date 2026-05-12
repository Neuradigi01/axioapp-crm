"""HTTP coverage for /api/v1/walk-ins CRUD + checkout.

Covers:
  - create / get / list / patch / delete
  - 422 on unknown contact
  - status transitions via PATCH
  - checkout stamps time_out + computes duration_min (generated col)
  - perm-gated writes
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
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


async def _seed_contact(org_id: uuid.UUID, phone: str = "+91 9000000001") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name="Walk-in tester",
                phone=phone,
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_create_get_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/walk-ins",
        json={
            "contact_id": str(contact_id),
            "requirement": "Looking for a 3-seater sofa",
            "budget": "75000.00",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "browsing"
    assert body["time_out"] is None
    assert body["duration_min"] is None
    walk_in_id = body["id"]

    got = await layered_client.get(
        f"/api/v1/walk-ins/{walk_in_id}", headers=headers
    )
    assert got.status_code == 200

    patch = await layered_client.patch(
        f"/api/v1/walk-ins/{walk_in_id}",
        json={"status": "interested", "notes": "Loved the Oak finish"},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["status"] == "interested"
    assert patch.json()["notes"] == "Loved the Oak finish"

    delete = await layered_client.delete(
        f"/api/v1/walk-ins/{walk_in_id}", headers=headers
    )
    assert delete.status_code == 204

    after = await layered_client.get(
        f"/api/v1/walk-ins/{walk_in_id}", headers=headers
    )
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_create_rejects_unknown_contact(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/walk-ins",
        json={"contact_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_checkout_stamps_time_out_and_duration(
    layered_client, seeded_admin
):
    """Checkout sets time_out=now; the generated column populates."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/walk-ins",
        json={"contact_id": str(contact_id)},
        headers=headers,
    )
    assert create.status_code == 201
    walk_in_id = create.json()["id"]

    checkout = await layered_client.patch(
        f"/api/v1/walk-ins/{walk_in_id}/checkout", headers=headers
    )
    assert checkout.status_code == 200
    body = checkout.json()
    assert body["time_out"] is not None
    # Generated column should be near zero (we just opened + closed).
    duration = float(body["duration_min"])
    assert 0 <= duration < 1.0  # less than a minute

    # Idempotent — second checkout doesn't change time_out.
    again = await layered_client.patch(
        f"/api/v1/walk-ins/{walk_in_id}/checkout", headers=headers
    )
    assert again.json()["time_out"] == body["time_out"]


@pytest.mark.asyncio
async def test_list_open_only_filter(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    open_id = (
        await layered_client.post(
            "/api/v1/walk-ins",
            json={"contact_id": str(contact_id)},
            headers=headers,
        )
    ).json()["id"]
    closed_id = (
        await layered_client.post(
            "/api/v1/walk-ins",
            json={"contact_id": str(contact_id)},
            headers=headers,
        )
    ).json()["id"]
    # Check the second one out so it has a time_out.
    await layered_client.patch(
        f"/api/v1/walk-ins/{closed_id}/checkout", headers=headers
    )

    all_resp = await layered_client.get("/api/v1/walk-ins", headers=headers)
    assert {w["id"] for w in all_resp.json()} == {open_id, closed_id}

    open_only = await layered_client.get(
        "/api/v1/walk-ins?open_only=true", headers=headers
    )
    assert [w["id"] for w in open_only.json()] == [open_id]


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read")
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/walk-ins",
        json={"contact_id": str(contact_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
