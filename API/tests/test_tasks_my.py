"""Coverage for `GET /api/v1/tasks/me`.

Asserts:
- only tasks assigned to the calling user come back;
- ordering is earliest-due first with nulls last;
- the `status` filter narrows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.users.models import User
from src.app.shared.security.password import hash_password


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
async def test_my_tasks_returns_only_callers_tasks_in_due_order(
    layered_client, seeded_admin
):
    """Caller sees only their own assigned tasks, earliest-due first."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user_a = seeded_admin["user"]
    role = seeded_admin["role"]
    await _grant(role.id, "tasks.read", "tasks.write")

    # Add a sibling user under the same org so we can prove
    # `/tasks/me` filters correctly.
    user_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            User(
                id=user_b_id,
                org_id=org.id,
                email="other@demo.local",
                password_hash=hash_password("Other@123"),
                full_name="Other",
                role_id=role.id,
                is_active=True,
            )
        )
        await session.commit()

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    in_2h = (now + timedelta(hours=2)).isoformat()
    in_3d = (now + timedelta(days=3)).isoformat()

    # 1) Self-assigned, due in 3 days
    resp = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "later", "due_at": in_3d},
        headers=headers,
    )
    assert resp.status_code == 201

    # 2) Self-assigned, due in 2 hours
    resp = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "sooner", "due_at": in_2h},
        headers=headers,
    )
    assert resp.status_code == 201

    # 3) Self-assigned, no due date (nulls last)
    resp = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "no-due"},
        headers=headers,
    )
    assert resp.status_code == 201

    # 4) Assigned to user B — should be invisible to user A's /me
    resp = await layered_client.post(
        "/api/v1/tasks",
        json={"title": "user-b-task", "assigned_to_id": str(user_b_id)},
        headers=headers,
    )
    assert resp.status_code == 201

    me = await layered_client.get("/api/v1/tasks/me", headers=headers)
    assert me.status_code == 200
    titles = [i["title"] for i in me.json()["items"]]
    assert titles == ["sooner", "later", "no-due"]
    assert "user-b-task" not in titles


@pytest.mark.asyncio
async def test_my_tasks_status_filter(layered_client, seeded_admin):
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

    for title in ("a", "b", "c"):
        resp = await layered_client.post(
            "/api/v1/tasks", json={"title": title}, headers=headers
        )
        assert resp.status_code == 201
        if title == "b":
            tid = resp.json()["id"]
            await layered_client.patch(
                f"/api/v1/tasks/{tid}",
                json={"status": "done"},
                headers=headers,
            )

    open_only = await layered_client.get(
        "/api/v1/tasks/me?status=open", headers=headers
    )
    titles = {i["title"] for i in open_only.json()["items"]}
    assert titles == {"a", "c"}

    done_only = await layered_client.get(
        "/api/v1/tasks/me?status=done", headers=headers
    )
    titles = {i["title"] for i in done_only.json()["items"]}
    assert titles == {"b"}
