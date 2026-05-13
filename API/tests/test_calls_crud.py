"""HTTP coverage for /api/v1/calls — CRUD + transcript + outcomes config.

Outcomes are config (not hardcoded) — the tests create them as needed
through the public endpoints so we exercise the same path the operator
uses, not a back-door insert.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
async def test_create_get_list_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "calls.read",
        "calls.write",
        "calls.outcomes.manage",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Outcome (config) creation.
    out = await layered_client.post(
        "/api/v1/call-outcomes",
        json={"key": "connected", "label": "Connected", "color": "#10b981"},
        headers=headers,
    )
    assert out.status_code == 201, out.text
    outcome_id = out.json()["id"]

    # Call creation.
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    create = await layered_client.post(
        "/api/v1/calls",
        json={
            "direction": "out",
            "started_at": now,
            "duration_sec": 180,
            "outcome_id": outcome_id,
            "notes": "Followed up on sofa quote",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["direction"] == "out"
    assert body["duration_sec"] == 180
    assert body["outcome_id"] == outcome_id
    call_id = body["id"]

    # List.
    listing = await layered_client.get("/api/v1/calls", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    # Patch.
    patch = await layered_client.patch(
        f"/api/v1/calls/{call_id}",
        json={"duration_sec": 200, "notes": "Updated note"},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["duration_sec"] == 200
    assert patch.json()["notes"] == "Updated note"

    # Delete.
    delete = await layered_client.delete(
        f"/api/v1/calls/{call_id}", headers=headers
    )
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_duplicate_outcome_key_returns_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "calls.read", "calls.outcomes.manage")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    first = await layered_client.post(
        "/api/v1/call-outcomes",
        json={"key": "no_answer", "label": "No Answer"},
        headers=headers,
    )
    assert first.status_code == 201
    dup = await layered_client.post(
        "/api/v1/call-outcomes",
        json={"key": "no_answer", "label": "Duplicate"},
        headers=headers,
    )
    assert dup.status_code == 409, dup.text


@pytest.mark.asyncio
async def test_transcript_upsert_replaces(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "calls.read", "calls.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    create = await layered_client.post(
        "/api/v1/calls",
        json={"direction": "in", "started_at": now, "duration_sec": 60},
        headers=headers,
    )
    assert create.status_code == 201
    call_id = create.json()["id"]

    # Initial PUT.
    first = await layered_client.put(
        f"/api/v1/calls/{call_id}/transcript",
        json={"text": "first version", "language": "en"},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    # Replace.
    second = await layered_client.put(
        f"/api/v1/calls/{call_id}/transcript",
        json={"text": "second version", "language": "hi"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["text"] == "second version"
    assert second.json()["language"] == "hi"

    # GET reflects latest.
    got = await layered_client.get(
        f"/api/v1/calls/{call_id}/transcript", headers=headers
    )
    assert got.status_code == 200
    assert got.json()["text"] == "second version"


@pytest.mark.asyncio
async def test_outcomes_manage_requires_perm(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Only `calls.read`, no `calls.outcomes.manage`.
    await _grant(seeded_admin["role"].id, "calls.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/call-outcomes",
        json={"key": "x", "label": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
