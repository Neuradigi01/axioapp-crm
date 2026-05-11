"""Integration test for `GET /api/v1/users/me`.

Verifies tenant isolation through the live HTTP surface:

  - Seed org A + org B, each with an admin role and one user.
  - Hit `/users/me` with org A context → user A returned.
  - Hit `/users/me` with org B context but user A's id → 404
    (the ORM tenant filter scopes the query to org B; user A is in A,
    so the lookup returns no row).

The test stands up its own `AsyncClient` around the *layered* app
(`src.app.main:app`) rather than the legacy template's, so the
new `/api/v1/users/...` routes are mounted.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Register layered models on the shared Base before create_all runs.
from src.app.core.permissions.models import Permission, Role, RolePermission  # noqa: F401
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.security.password import hash_password
from src.models import Base
from tests.conftest import TestSession, test_engine, _patch_all_async_sessions, _restore_all_async_sessions


@pytest_asyncio.fixture
async def layered_client():
    """AsyncClient wrapped around the layered FurnitureCRM ASGI app."""
    from src.app.main import app

    originals = _patch_all_async_sessions()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    _restore_all_async_sessions(originals)


@pytest_asyncio.fixture
async def two_orgs_with_admin():
    """Seed two orgs, each with an admin role + one user."""
    org_a = Organization(
        id=uuid.uuid4(), name="Org A", slug=f"a-{uuid.uuid4().hex[:6]}"
    )
    org_b = Organization(
        id=uuid.uuid4(), name="Org B", slug=f"b-{uuid.uuid4().hex[:6]}"
    )
    role_a = Role(id=uuid.uuid4(), org_id=org_a.id, name="admin", is_system=True)
    role_b = Role(id=uuid.uuid4(), org_id=org_b.id, name="admin", is_system=True)
    user_a = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="a@example.com",
        password_hash=hash_password("p"),
        full_name="A User",
        role_id=role_a.id,
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        org_id=org_b.id,
        email="b@example.com",
        password_hash=hash_password("p"),
        full_name="B User",
        role_id=role_b.id,
        is_active=True,
    )

    async with TestSession() as session:
        # Flush in dependency order: orgs → roles → users.
        # `add_all` with mixed parents/children doesn't always topo-sort
        # when only column-level FKs are declared (no `relationship()`).
        session.add_all([org_a, org_b])
        await session.flush()
        session.add_all([role_a, role_b])
        await session.flush()
        session.add_all([user_a, user_b])
        await session.commit()

    return {"org_a": org_a, "org_b": org_b, "user_a": user_a, "user_b": user_b}


@pytest.mark.asyncio
async def test_users_me_returns_user_in_own_org(layered_client, two_orgs_with_admin):
    user_a = two_orgs_with_admin["user_a"]
    org_a = two_orgs_with_admin["org_a"]

    resp = await layered_client.get(
        "/api/v1/users/me",
        headers={"X-Org-Id": str(org_a.id), "X-User-Id": str(user_a.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(user_a.id)
    assert body["org_id"] == str(org_a.id)
    assert body["email"] == "a@example.com"
    assert body["role_name"] == "admin"
    assert body["permission_keys"] == []  # no role_permissions seeded


@pytest.mark.asyncio
async def test_users_me_404_when_user_id_belongs_to_other_org(
    layered_client, two_orgs_with_admin
):
    """User A under org B's context → tenant filter hides A → 404."""
    user_a = two_orgs_with_admin["user_a"]
    org_b = two_orgs_with_admin["org_b"]

    resp = await layered_client.get(
        "/api/v1/users/me",
        headers={"X-Org-Id": str(org_b.id), "X-User-Id": str(user_a.id)},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_users_me_401_when_no_context(layered_client):
    resp = await layered_client.get("/api/v1/users/me")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_users_me_401_when_only_org_supplied(layered_client, two_orgs_with_admin):
    org_a = two_orgs_with_admin["org_a"]
    resp = await layered_client.get(
        "/api/v1/users/me",
        headers={"X-Org-Id": str(org_a.id)},
    )
    assert resp.status_code == 401, resp.text
