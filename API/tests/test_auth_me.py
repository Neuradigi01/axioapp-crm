"""Tests for `/api/v1/users/me` under the new JWT auth contract."""
from __future__ import annotations

import pytest


async def _login(client, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_me_with_valid_token_returns_200(layered_client, seeded_admin):
    token = await _login(
        layered_client,
        seeded_admin["org"].slug,
        seeded_admin["user"].email,
        seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == seeded_admin["user"].email


@pytest.mark.asyncio
async def test_me_without_token_returns_401(layered_client):
    resp = await layered_client.get("/api/v1/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_garbage_token_returns_401(layered_client):
    resp = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_revoked_token_returns_401(layered_client, seeded_admin):
    token = await _login(
        layered_client,
        seeded_admin["org"].slug,
        seeded_admin["user"].email,
        seeded_admin["password"],
    )
    # The token works before logout.
    ok = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert ok.status_code == 200

    # Log out revokes the session.
    out = await layered_client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert out.status_code == 200

    # Same token now rejected.
    after = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert after.status_code == 401
