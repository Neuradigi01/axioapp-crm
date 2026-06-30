"""Integration tests for `/api/v1/users/me` and `/api/v1/users`.

These now drive the layered app via real JWT auth (via
`POST /auth/login`). The earlier dev-header path is intentionally
insufficient since Step 1.6 — `get_current_user` requires a non-null
`token_id`, which only `/auth/login` produces.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_users_me_with_valid_token(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    password = seeded_admin["password"]

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password, "org_slug": org.slug},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    me = await layered_client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == str(user.id)
    assert body["org_id"] == str(org.id)
    assert body["email"] == user.email
    assert body["role_name"] == "admin"


@pytest.mark.asyncio
async def test_users_me_without_token_is_401(layered_client):
    resp = await layered_client.get("/api/v1/users/me")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_users_me_dev_headers_alone_are_401(layered_client, seeded_admin):
    """The dev `X-Org-Id` / `X-User-Id` shortcut populates `org_id` and
    `user_id` but NOT `token_id`. Without a token_id (and the matching
    `auth_sessions` row), `get_current_user` returns 401 — which is the
    point: a real session is mandatory."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    resp = await layered_client.get(
        "/api/v1/users/me",
        headers={"X-Org-Id": str(org.id), "X-User-Id": str(user.id)},
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_users_list_scoped_to_active_org(layered_client, seeded_admin):
    """A user logged in to org A only sees users from org A in /users."""
    import uuid as _uuid

    from src.app.core.permissions.models import Role
    from src.app.core.tenants.models import Organization
    from src.app.core.users.models import User
    from src.app.shared.security.password import hash_password
    from tests.conftest import TestSession

    other_org = Organization(id=_uuid.uuid4(), name="Other", slug=f"other-{_uuid.uuid4().hex[:6]}")
    other_role = Role(id=_uuid.uuid4(), org_id=other_org.id, name="admin", is_system=True)
    other_user = User(
        id=_uuid.uuid4(),
        org_id=other_org.id,
        email="other@example.com",
        password_hash=hash_password("x"),
        full_name="Other",
        role_id=other_role.id,
        is_active=True,
    )
    async with TestSession() as session:
        session.add(other_org)
        await session.flush()
        session.add(other_role)
        await session.flush()
        session.add(other_user)
        await session.commit()

    # Log in as seeded_admin (org A) → list users → should only see admin.
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": seeded_admin["password"], "org_slug": org.slug},
    )
    token = resp.json()["access_token"]

    listing = await layered_client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
    )
    assert listing.status_code == 200, listing.text
    emails = sorted(u["email"] for u in listing.json())
    assert emails == [user.email]  # NOT other@example.com
