"""Tests for `POST /api/v1/auth/register` after the Step 2 split.

Register now creates the user + a placeholder organization with
`template_id="pending"`. No pack data is seeded; the response carries
`needs_onboarding=true`.

Distinct from the legacy `register_with_new_org` covered by other
suites — this is the new self-signup stage 1.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.app.core.auth.tokens import decode_token
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, UserInfo


@pytest.mark.asyncio
async def test_register_creates_user_and_pending_org(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/register",
        json={
            "email": "founder@onboarding-test.local",
            "password": "Owner@123",
            "first_name": "Acme",
            "last_name": "Co",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["needs_onboarding"] is True
    assert body["organization_slug"]
    assert body["role_name"] == "Owner"

    # JWT is a normal admin token — same shape as login. It carries a
    # real org_id (the pending placeholder). `needs_onboarding` lives
    # in the response body and `/users/me`, NOT in the JWT.
    claims = decode_token(body["access_token"])
    assert str(claims.org_id) == body["organization_id"]
    assert claims.scope == "admin"


@pytest.mark.asyncio
async def test_register_org_is_template_id_pending(layered_client):
    from tests.conftest import TestSession

    resp = await layered_client.post(
        "/api/v1/auth/register",
        json={
            "email": "founder2@onboarding-test.local",
            "password": "Owner@123",
            "first_name": "Beta",
            "last_name": "Co",
        },
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["organization_id"]

    async with TestSession() as session:
        org = (
            await session.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one()
        assert org.template_id == "pending"
        assert org.name == "Beta's Workspace"
        assert org.created_via == "normal_signup"


@pytest.mark.asyncio
async def test_register_creates_membership_and_user_info(layered_client):
    from tests.conftest import TestSession

    resp = await layered_client.post(
        "/api/v1/auth/register",
        json={
            "email": "founder3@onboarding-test.local",
            "password": "Owner@123",
            "first_name": "Gamma",
            "last_name": "Co",
        },
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["organization_id"]

    async with TestSession() as session:
        info = (
            await session.execute(
                select(UserInfo).where(UserInfo.email == "founder3@onboarding-test.local")
            )
        ).scalar_one()
        member = (
            await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.user_member_id == info.member_id,
                )
            )
        ).scalar_one()
        assert member.is_active is True
        assert member.status == "active"


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(layered_client):
    body = {
        "email": "dup@onboarding-test.local",
        "password": "Owner@123",
        "first_name": "Dup",
        "last_name": "Co",
    }
    first = await layered_client.post("/api/v1/auth/register", json=body)
    assert first.status_code == 201, first.text

    second = await layered_client.post("/api/v1/auth/register", json=body)
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_register_silently_ignores_legacy_org_name(layered_client):
    """Old clients that send `organization_name` should still succeed —
    Pydantic v2 default `extra="ignore"` drops the field."""
    resp = await layered_client.post(
        "/api/v1/auth/register",
        json={
            "email": "legacy@onboarding-test.local",
            "password": "Owner@123",
            "first_name": "Legacy",
            "last_name": "Co",
            "organization_name": "Some Old Name",
        },
    )
    assert resp.status_code == 201, resp.text
    # Org is created with the placeholder name, not the legacy submission.
    from tests.conftest import TestSession

    async with TestSession() as session:
        org = (
            await session.execute(
                select(Organization).where(Organization.id == resp.json()["organization_id"])
            )
        ).scalar_one()
        assert org.name == "Legacy's Workspace"


@pytest.mark.asyncio
async def test_register_users_me_returns_needs_onboarding_true(layered_client):
    resp = await layered_client.post(
        "/api/v1/auth/register",
        json={
            "email": "me-flag@onboarding-test.local",
            "password": "Owner@123",
            "first_name": "MeFlag",
            "last_name": "Co",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    me = await layered_client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["needs_onboarding"] is True
    assert me.json()["org"]["template_id"] == "pending"
