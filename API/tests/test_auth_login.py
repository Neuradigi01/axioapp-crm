"""Tests for `POST /api/v1/auth/login`."""
from __future__ import annotations

import pytest

from src.app.core.auth.tokens import decode_token


@pytest.mark.asyncio
async def test_login_with_correct_credentials_returns_token(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "Admin@123",
            "org_slug": org.slug,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]

    claims = decode_token(body["access_token"])
    assert claims.user_id == user.id
    assert claims.org_id == org.id


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_401(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "not-it", "org_slug": org.slug},
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_with_unknown_email_is_401(layered_client, seeded_admin):
    org = seeded_admin["org"]
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@demo.local", "password": "x", "org_slug": org.slug},
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_with_unknown_org_slug_is_401(layered_client, seeded_admin):
    user = seeded_admin["user"]
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Admin@123", "org_slug": "no-such-org"},
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_with_inactive_user_is_401(layered_client, seeded_admin):
    """Inactive users can't log in even with correct creds."""
    from tests.conftest import TestSession
    from sqlalchemy import update
    from src.app.core.users.models import User

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    async with TestSession() as session:
        await session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await session.commit()

    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Admin@123", "org_slug": org.slug},
    )
    assert resp.status_code == 401, resp.text
