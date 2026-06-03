"""Tests for `POST /api/v1/auth/onboarding/complete`.

Finalizes the pending-pack org created by `POST /auth/register`:
renames it, sets the chosen `pack_id`, runs the matching pack
installer, and rotates the JWT.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from src.app.core.auth.tokens import decode_token
from src.app.core.permissions.models import Role
from src.app.core.pipelines.models import Pipeline
from src.app.core.tenants.models import Organization


async def _register_pending(client, email: str, first: str = "Acme") -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Owner@123",
            "first_name": first,
            "last_name": "Co",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_onboarding_complete_furniture_happy_path(layered_client):
    from tests.conftest import TestSession

    token = await _register_pending(
        layered_client, "furniture@onboarding-test.local"
    )

    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={
            "organization_name": "Acme Furniture",
            "pack_id": "furniture",
            "country": "India",
            "team_size": "1-5",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_onboarding"] is False
    assert body["organization_slug"]

    # Fresh JWT carries the same org_id as the rotated session.
    claims = decode_token(body["access_token"])
    assert str(claims.org_id) == body["organization_id"]

    async with TestSession() as session:
        org = (
            await session.execute(
                select(Organization).where(
                    Organization.id == body["organization_id"]
                )
            )
        ).scalar_one()
        assert org.name == "Acme Furniture"
        assert org.pack_id == "furniture"
        # Pack tax_rate for furniture is 18%.
        assert float(org.tax_rate) == 18.0

        # Furniture pack ships a `leads` pipeline AND a `custom_orders`
        # pipeline. Spot-check one to prove the installer ran.
        pipelines = (
            await session.execute(
                select(Pipeline).where(Pipeline.org_id == org.id)
            )
        ).scalars().all()
        keys = {p.key for p in pipelines}
        assert "leads" in keys or "custom_orders" in keys


@pytest.mark.asyncio
async def test_onboarding_complete_base_happy_path(layered_client):
    from tests.conftest import TestSession

    token = await _register_pending(
        layered_client, "base@onboarding-test.local", first="Base"
    )

    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={
            "organization_name": "Base Workspace",
            "pack_id": "base",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    async with TestSession() as session:
        org = (
            await session.execute(
                select(Organization).where(
                    Organization.id == body["organization_id"]
                )
            )
        ).scalar_one()
        assert org.pack_id == "base"

        # Owner role still present after pack install (role_templates
        # installed during register; pack installer is additive).
        owner = (
            await session.execute(
                select(Role).where(
                    Role.org_id == org.id, Role.name == "Owner"
                )
            )
        ).scalar_one_or_none()
        assert owner is not None


@pytest.mark.asyncio
async def test_onboarding_complete_rejects_coming_soon_pack(layered_client):
    token = await _register_pending(
        layered_client, "coming-soon@onboarding-test.local", first="Coming"
    )

    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={
            "organization_name": "Real Estate Inc",
            "pack_id": "real_estate",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error"] == "pack_not_available"


@pytest.mark.asyncio
async def test_onboarding_complete_rejects_unknown_pack(layered_client):
    token = await _register_pending(
        layered_client, "unknown-pack@onboarding-test.local", first="Unknown"
    )

    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={
            "organization_name": "Nope Inc",
            "pack_id": "blockchain",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error"] == "pack_not_found"


@pytest.mark.asyncio
async def test_onboarding_complete_rejects_empty_org_name(layered_client):
    token = await _register_pending(
        layered_client, "empty-name@onboarding-test.local", first="Empty"
    )

    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={"organization_name": "", "pack_id": "base"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # min_length=1 → Pydantic 422.
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_onboarding_complete_409_after_already_onboarded(layered_client):
    token = await _register_pending(
        layered_client, "twice@onboarding-test.local", first="Twice"
    )

    first = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={"organization_name": "First", "pack_id": "base"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200, first.text
    new_token = first.json()["access_token"]

    # The original token is now revoked (JWT rotated) — use the new one
    # to attempt a second onboarding.
    second = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={"organization_name": "Second", "pack_id": "furniture"},
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["error"] == "already_onboarded"


@pytest.mark.asyncio
async def test_users_me_flips_to_not_needs_onboarding(layered_client):
    token = await _register_pending(
        layered_client, "me-after@onboarding-test.local", first="MeAfter"
    )
    finish = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={"organization_name": "Done Inc", "pack_id": "base"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert finish.status_code == 200, finish.text
    new_token = finish.json()["access_token"]

    me = await layered_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["needs_onboarding"] is False
    assert body["org"]["pack_id"] == "base"
    assert body["org"]["name"] == "Done Inc"


@pytest.mark.asyncio
async def test_onboarding_complete_requires_auth(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/onboarding/complete",
        json={"organization_name": "X", "pack_id": "base"},
    )
    assert resp.status_code == 401
