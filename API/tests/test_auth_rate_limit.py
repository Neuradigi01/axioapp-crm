"""Test the login rate limiter (10 attempts / minute / IP)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_eleventh_login_attempt_in_a_window_is_429(layered_client, seeded_admin):
    org_slug = seeded_admin["org"].slug
    bad_body = {"email": "wrong@x", "password": "x", "org_slug": org_slug}

    # First 10 should be rejected on credentials (401), but allowed by the limiter.
    for _ in range(10):
        r = await layered_client.post("/api/v1/auth/login", json=bad_body)
        assert r.status_code == 401, r.text

    # 11th hit the bucket.
    r = await layered_client.post("/api/v1/auth/login", json=bad_body)
    assert r.status_code == 429, r.text
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_rate_limit_counts_successful_logins_too(layered_client, seeded_admin):
    """The limiter is per-IP irrespective of whether the credentials were good."""
    org_slug = seeded_admin["org"].slug
    email = seeded_admin["user"].email
    pwd = seeded_admin["password"]

    for _ in range(10):
        r = await layered_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": pwd, "org_slug": org_slug},
        )
        assert r.status_code == 200, r.text

    r = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": pwd, "org_slug": org_slug},
    )
    assert r.status_code == 429, r.text


@pytest.mark.asyncio
async def test_rate_limit_reset_releases_block(layered_client, seeded_admin):
    """Resetting the limiter (per-test cleanup proxy) unblocks the IP."""
    from src.app.shared.rate_limit import login_limiter

    org_slug = seeded_admin["org"].slug
    bad = {"email": "x@x", "password": "x", "org_slug": org_slug}

    for _ in range(11):
        await layered_client.post("/api/v1/auth/login", json=bad)
    final_blocked = await layered_client.post("/api/v1/auth/login", json=bad)
    assert final_blocked.status_code == 429

    login_limiter.reset()

    after = await layered_client.post("/api/v1/auth/login", json=bad)
    assert after.status_code == 401  # back to credential failure, not 429
