"""Tests for `POST /api/v1/auth/refresh`."""
from __future__ import annotations

import pytest

from src.app.core.auth.tokens import decode_token


@pytest.mark.asyncio
async def test_refresh_returns_new_token_and_revokes_old(layered_client, seeded_admin):
    login = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": seeded_admin["user"].email,
            "password": seeded_admin["password"],
            "org_slug": seeded_admin["org"].slug,
        },
    )
    old_token = login.json()["access_token"]
    old_claims = decode_token(old_token)

    refresh = await layered_client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert refresh.status_code == 200, refresh.text
    new_token = refresh.json()["access_token"]
    new_claims = decode_token(new_token)

    assert new_token != old_token
    assert new_claims.token_id != old_claims.token_id
    assert new_claims.user_id == old_claims.user_id
    assert new_claims.org_id == old_claims.org_id

    # The new token works.
    ok = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert ok.status_code == 200, ok.text

    # The old token is revoked.
    rejected = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert rejected.status_code == 401, rejected.text


@pytest.mark.asyncio
async def test_refresh_without_bearer_returns_401(layered_client):
    resp = await layered_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_garbage_token_returns_401(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/refresh", headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401
