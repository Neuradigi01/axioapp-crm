"""HTTP-level coverage for the saved_views module (Step 7).

Covers the seven acceptance points from the step file:

  - create view (owner) → 201 + appears in list
  - duplicate (owner+entity+name) → 409
  - update / delete by non-owner → 403
  - shared view visible to another user in the same org
  - shared view NOT visible cross-tenant
  - delete by owner → 204; subsequent list omits
  - malformed `config` shape → 422

The fixture helpers (`_grant`, `_login`, `_make_second_user`) come
from existing test modules so the seeding semantics stay in lockstep
with the leads suite.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.permissions.models import Role
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo, UserLogin

from tests.test_leads_crud import _grant, _login


async def _make_second_user_in_org(
    org_id: uuid.UUID,
    *,
    email: str,
    password: str,
    role_name: str = "rep",
) -> dict:
    """Mint a second user inside the same org with a fresh role.

    Mirrors `_make_second_user` from `test_leads_row_level_scope.py`.
    Returns dict with `user`, `role`, `password`.
    """
    from tests.conftest import TestSession

    role_uuid = uuid.uuid4()
    user_uuid = uuid.uuid4()
    login_handle = f"test-{uuid.uuid4().hex[:8]}"

    role = Role(id=role_uuid, org_id=org_id, name=role_name, is_system=False)
    user_login = UserLogin(
        user_id=login_handle,
        password=hash_password(password),
        is_active=True,
    )

    async with TestSession() as session:
        session.add(role)
        await session.flush()

        session.add(user_login)
        await session.flush()

        await session.execute(
            sql_text("UPDATE tbl_user_login SET legacy_uuid = :uuid WHERE id = :id"),
            {"uuid": str(user_uuid), "id": user_login.id},
        )
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:uuid) ON CONFLICT DO NOTHING"),
            {"uuid": str(user_uuid)},
        )

        session.add(
            LegacyUserInfo(
                member_id=user_login.id,
                first_name="Second",
                last_name="User",
                email=email,
                mobile_no="0000000002",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_member_id=user_login.id,
                role_id=role_uuid,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()

        result = await session.execute(
            select(User).where(User.id == user_login.id)
        )
        user = result.scalar_one()

    return {"user": user, "role": role, "password": password}


async def _make_org(name: str = "Other") -> uuid.UUID:
    """Create a bare sibling org for cross-tenant tests. No users."""
    from tests.conftest import TestSession

    org_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_id, name=name, slug=f"{name.lower()}-{org_id.hex[:6]}"
            )
        )
        await session.commit()
    return org_id


_SAMPLE_CONFIG = {
    "filter": {"all": [{"field": "status", "op": "eq", "value": "active"}]},
    "sort": "lead_score",
    "order": "desc",
    "view": "list",
}


# --- 1. Create + list (happy path) -----------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_view(layered_client, seeded_admin):
    """Owner creates a view → 201 → appears in the list response."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/saved-views",
        json={
            "entity": "leads",
            "name": "Hot qualified",
            "config": _SAMPLE_CONFIG,
            "shared": False,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Hot qualified"
    assert body["entity"] == "leads"
    assert body["shared"] is False
    assert body["config"]["sort"] == "lead_score"

    listed = await layered_client.get(
        "/api/v1/saved-views?entity=leads", headers=headers
    )
    assert listed.status_code == 200
    items = listed.json()
    assert any(v["id"] == body["id"] for v in items)


# --- 2. Duplicate name -----------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_name_is_conflict(layered_client, seeded_admin):
    """Same (owner, entity, name) → 409."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "entity": "leads",
        "name": "Dupes",
        "config": _SAMPLE_CONFIG,
    }
    first = await layered_client.post(
        "/api/v1/saved-views", json=payload, headers=headers
    )
    assert first.status_code == 201

    second = await layered_client.post(
        "/api/v1/saved-views", json=payload, headers=headers
    )
    assert second.status_code == 409, second.text


# --- 3. Non-owner update is forbidden -------------------------------------


@pytest.mark.asyncio
async def test_non_owner_cannot_update(layered_client, seeded_admin):
    org = seeded_admin["org"]
    owner = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    other = await _make_second_user_in_org(
        org.id, email="rep@demo.local", password="Rep@1234"
    )
    await _grant(other["role"].id, "saved_views.use")

    owner_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=owner.email,
        password=seeded_admin["password"],
    )
    other_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=other["user"].email,
        password=other["password"],
    )

    # Owner creates a SHARED view so the other user can see it.
    created = await layered_client.post(
        "/api/v1/saved-views",
        json={
            "entity": "leads",
            "name": "Shared view",
            "config": _SAMPLE_CONFIG,
            "shared": True,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 201, created.text
    view_id = created.json()["id"]

    # Other user tries to PATCH the shared view → 403.
    patch_resp = await layered_client.patch(
        f"/api/v1/saved-views/{view_id}",
        json={"name": "Hijack"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert patch_resp.status_code == 403, patch_resp.text


# --- 4. Shared view visible to another user in same org -------------------


@pytest.mark.asyncio
async def test_shared_view_visible_to_another_user_same_org(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    owner = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    other = await _make_second_user_in_org(
        org.id, email="rep@demo.local", password="Rep@1234"
    )
    await _grant(other["role"].id, "saved_views.use")

    owner_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=owner.email,
        password=seeded_admin["password"],
    )
    await layered_client.post(
        "/api/v1/saved-views",
        json={
            "entity": "leads",
            "name": "Team scoreboard",
            "config": _SAMPLE_CONFIG,
            "shared": True,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    other_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=other["user"].email,
        password=other["password"],
    )
    listed = await layered_client.get(
        "/api/v1/saved-views?entity=leads",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert listed.status_code == 200
    names = [v["name"] for v in listed.json()]
    assert "Team scoreboard" in names


# --- 5. Cross-tenant invisibility -----------------------------------------


@pytest.mark.asyncio
async def test_shared_view_invisible_cross_tenant(
    layered_client, seeded_admin
):
    """Org B's shared view does NOT appear in org A's list."""
    from tests.conftest import TestSession

    from src.app.core.saved_views.models import SavedView
    from src.app.shared.context import RequestContext, reset_context, set_context

    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    # Spin up org B with a stub user UUID and a shared view.
    org_b_id = await _make_org("OrgB")
    stub_user_b = uuid.uuid4()
    token_ctx = set_context(RequestContext(org_id=org_b_id))
    try:
        async with TestSession() as session:
            session.add(
                SavedView(
                    org_id=org_b_id,
                    owner_user_id=stub_user_b,
                    entity="leads",
                    name="Org B secret",
                    config=_SAMPLE_CONFIG,
                    shared=True,
                )
            )
            await session.commit()
    finally:
        reset_context(token_ctx)

    token = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    listed = await layered_client.get(
        "/api/v1/saved-views?entity=leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    names = [v["name"] for v in listed.json()]
    assert "Org B secret" not in names


# --- 6. Delete: non-owner 403, owner 204 ---------------------------------


@pytest.mark.asyncio
async def test_delete_only_by_owner(layered_client, seeded_admin):
    org = seeded_admin["org"]
    owner = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    other = await _make_second_user_in_org(
        org.id, email="rep@demo.local", password="Rep@1234"
    )
    await _grant(other["role"].id, "saved_views.use")

    owner_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=owner.email,
        password=seeded_admin["password"],
    )
    other_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=other["user"].email,
        password=other["password"],
    )

    created = await layered_client.post(
        "/api/v1/saved-views",
        json={
            "entity": "leads",
            "name": "Deletable",
            "config": _SAMPLE_CONFIG,
            "shared": True,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    view_id = created.json()["id"]

    # Non-owner → 403.
    bad = await layered_client.delete(
        f"/api/v1/saved-views/{view_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert bad.status_code == 403

    # Owner → 204; list afterwards omits it.
    good = await layered_client.delete(
        f"/api/v1/saved-views/{view_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert good.status_code == 204
    listed = await layered_client.get(
        "/api/v1/saved-views?entity=leads",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert all(v["id"] != view_id for v in listed.json())


# --- 7. Malformed config shape -------------------------------------------


@pytest.mark.asyncio
async def test_malformed_config_rejected(layered_client, seeded_admin):
    """Unknown keys inside `config` are 422 — guards against arbitrary
    blobs landing in JSONB."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "saved_views.use")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/saved-views",
        json={
            "entity": "leads",
            "name": "Bad",
            "config": {"not_a_real_key": 42},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text
