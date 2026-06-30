"""HTTP-level CRUD coverage for /api/v1/tasks.

Exercises create / get / list-for-entity / patch / delete plus the
permission gates and the "related entity is paired" validator.
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
async def test_create_list_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = uuid.uuid4()
    create = await layered_client.post(
        "/api/v1/tasks",
        json={
            "title": "Follow up with Asha",
            "related_entity_type": "contact",
            "related_entity_id": str(contact_id),
            "priority": "high",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["title"] == "Follow up with Asha"
    assert body["status"] == "open"
    assert body["priority"] == "high"
    # When `assigned_to_id` is omitted, the caller is the assignee.
    assert body["assigned_to_id"] == str(user.id)
    task_id = body["id"]

    listed = await layered_client.get(
        f"/api/v1/tasks?related_entity_type=contact&related_entity_id={contact_id}",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patch = await layered_client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "done"},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "done"

    delete = await layered_client.delete(f"/api/v1/tasks/{task_id}", headers=headers)
    assert delete.status_code == 204

    after = await layered_client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_related_pair_must_be_both_or_neither(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    bad = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "Orphan", "related_entity_type": "contact"},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text

    # Both null is fine (a free-standing task).
    ok = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "Free-standing"},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_filtered_by_status(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "tasks.read", "tasks.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = uuid.uuid4()
    for title, status_value in (("a", None), ("b", "done"), ("c", None)):
        create = await layered_client.post(
            "/api/v1/tasks",
            json={
                "title": title,
                "related_entity_type": "contact",
                "related_entity_id": str(contact_id),
            },
            headers=headers,
        )
        assert create.status_code == 201
        if status_value is not None:
            tid = create.json()["id"]
            await layered_client.patch(
                f"/api/v1/tasks/{tid}",
                json={"status": status_value},
                headers=headers,
            )

    open_only = await layered_client.get(
        f"/api/v1/tasks?related_entity_type=contact&related_entity_id={contact_id}&status=open",
        headers=headers,
    )
    assert open_only.status_code == 200
    titles = {i["title"] for i in open_only.json()["items"]}
    assert titles == {"a", "c"}
