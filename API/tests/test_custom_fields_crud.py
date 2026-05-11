"""HTTP-level coverage for /api/v1/custom-fields CRUD on `source=user`.

Grants `custom_fields.read` + `custom_fields.write` to the seeded admin,
logs in, and exercises create / list / patch / delete on user-source
fields. Source-rule edge cases live in `test_custom_fields_source_rules.py`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


async def _grant_custom_fields(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module="custom_fields", description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
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
async def test_create_list_update_delete_user_field(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant_custom_fields(
        seeded_admin["role"].id, "custom_fields.read", "custom_fields.write"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Create
    create = await layered_client.post(
        "/api/v1/custom-fields",
        json={
            "entity_type": "contact",
            "field_key": "dob",
            "field_label": "Date of Birth",
            "field_type": "date",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["source"] == "user"
    assert body["field_key"] == "dob"
    assert body["entity_type"] == "contact"
    field_id = body["id"]

    # List
    listed = await layered_client.get(
        "/api/v1/custom-fields?entity_type=contact", headers=headers
    )
    assert listed.status_code == 200
    keys = [item["field_key"] for item in listed.json()]
    assert "dob" in keys

    # Update label + order
    patch = await layered_client.patch(
        f"/api/v1/custom-fields/{field_id}",
        json={"field_label": "DOB", "display_order": 5},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["field_label"] == "DOB"
    assert patch.json()["display_order"] == 5

    # Delete
    delete = await layered_client.delete(
        f"/api/v1/custom-fields/{field_id}", headers=headers
    )
    assert delete.status_code == 204

    # Confirm gone
    listed_again = await layered_client.get(
        "/api/v1/custom-fields?entity_type=contact", headers=headers
    )
    assert "dob" not in [item["field_key"] for item in listed_again.json()]


@pytest.mark.asyncio
async def test_duplicate_field_key_returns_409(layered_client, seeded_admin):
    """The unique (org_id, entity_type, field_key) index surfaces as 409."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant_custom_fields(
        seeded_admin["role"].id, "custom_fields.read", "custom_fields.write"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "entity_type": "contact",
        "field_key": "nickname",
        "field_label": "Nickname",
        "field_type": "text",
    }
    first = await layered_client.post(
        "/api/v1/custom-fields", json=payload, headers=headers
    )
    assert first.status_code == 201

    second = await layered_client.post(
        "/api/v1/custom-fields", json=payload, headers=headers
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_create_rejects_bad_field_key(layered_client, seeded_admin):
    """Field-key regex rejects uppercase / hyphen / leading digit."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant_custom_fields(
        seeded_admin["role"].id, "custom_fields.write"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for bad in ("BadKey", "with-hyphen", "1starts_with_digit", "x"):
        resp = await layered_client.post(
            "/api/v1/custom-fields",
            json={
                "entity_type": "contact",
                "field_key": bad,
                "field_label": "X",
                "field_type": "text",
            },
            headers=headers,
        )
        assert resp.status_code == 422, (bad, resp.text)


@pytest.mark.asyncio
async def test_select_field_requires_choices(layered_client, seeded_admin):
    """`select`/`multiselect` must declare options.choices."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant_custom_fields(
        seeded_admin["role"].id, "custom_fields.write"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    missing = await layered_client.post(
        "/api/v1/custom-fields",
        json={
            "entity_type": "contact",
            "field_key": "tshirt_size",
            "field_label": "T-shirt size",
            "field_type": "select",
        },
        headers=headers,
    )
    assert missing.status_code == 422, missing.text

    ok = await layered_client.post(
        "/api/v1/custom-fields",
        json={
            "entity_type": "contact",
            "field_key": "tshirt_size",
            "field_label": "T-shirt size",
            "field_type": "select",
            "options": {"choices": ["S", "M", "L"]},
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    """A user without `custom_fields.write` is 403 on POST."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Grant only `read` — the write attempt should still fail.
    await _grant_custom_fields(seeded_admin["role"].id, "custom_fields.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/custom-fields",
        json={
            "entity_type": "contact",
            "field_key": "anything",
            "field_label": "Anything",
            "field_type": "text",
        },
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
