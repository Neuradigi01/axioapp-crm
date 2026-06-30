"""HTTP coverage for /api/v1/reviews — CRUD + reply + escalate."""

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


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_list_get_update_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read", "reviews.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Create
    create = await layered_client.post(
        "/api/v1/reviews",
        json={
            "source": "google",
            "source_id": "g-abc",
            "rating": 4,
            "text": "Great service, fast delivery.",
            "tags": ["delivery", "service"],
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["rating"] == 4
    assert body["status"] == "pending_reply"
    assert body["tags"] == ["delivery", "service"]
    rid = body["id"]

    # List
    listing = await layered_client.get("/api/v1/reviews", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    # Filter by rating
    by_rating = await layered_client.get("/api/v1/reviews?rating=4", headers=headers)
    assert by_rating.json()["total"] == 1
    miss = await layered_client.get("/api/v1/reviews?rating=1", headers=headers)
    assert miss.json()["total"] == 0

    # Patch
    patch = await layered_client.patch(
        f"/api/v1/reviews/{rid}",
        json={"text": "Updated", "tags": ["delivery"]},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["text"] == "Updated"
    assert patch.json()["tags"] == ["delivery"]

    # Delete
    delete = await layered_client.delete(f"/api/v1/reviews/{rid}", headers=headers)
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_reply_flips_status_to_replied(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read", "reviews.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/reviews",
        json={"source": "google", "rating": 5, "text": "Loved it"},
        headers=headers,
    )
    rid = create.json()["id"]
    assert create.json()["status"] == "pending_reply"

    reply = await layered_client.post(
        f"/api/v1/reviews/{rid}/reply",
        json={"text": "Thanks for the kind words!"},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["status"] == "replied"
    assert body["reply_text"] == "Thanks for the kind words!"
    assert body["replied_at"] is not None
    assert body["replied_by_id"] == str(user.id)


@pytest.mark.asyncio
async def test_escalate_flips_status(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read", "reviews.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/reviews",
        json={"source": "facebook", "rating": 1, "text": "Terrible"},
        headers=headers,
    )
    rid = create.json()["id"]

    esc = await layered_client.post(
        f"/api/v1/reviews/{rid}/escalate",
        json={"reason": "Needs owner attention"},
        headers=headers,
    )
    assert esc.status_code == 200
    assert esc.json()["status"] == "escalated"


@pytest.mark.asyncio
async def test_rating_out_of_range_returns_422(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read", "reviews.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/reviews",
        json={"source": "google", "rating": 9},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Only read
    await _grant(seeded_admin["role"].id, "reviews.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/reviews",
        json={"source": "google", "rating": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
