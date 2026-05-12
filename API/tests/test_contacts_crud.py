"""HTTP-level coverage for /api/v1/contacts CRUD.

Grants `contacts.read` + `contacts.write` (and the matching
`custom_fields.*` keys for the validation-driver test) to the seeded
admin, logs in, and exercises create / list / patch / delete plus the
custom-data validation rules + tenant isolation.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
    FieldType,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.shared.context import RequestContext, reset_context, set_context


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_field(
    org_id: uuid.UUID,
    *,
    field_key: str,
    field_type: FieldType,
    is_required: bool = False,
    options: dict | None = None,
) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            session.add(
                CustomFieldDefinition(
                    org_id=org_id,
                    entity_type="contact",
                    field_key=field_key,
                    field_label=field_key.replace("_", " ").title(),
                    field_type=field_type,
                    options=options,
                    is_required=is_required,
                    source=FieldSource.system,
                )
            )
            await session.commit()
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_create_list_update_delete_contact(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Create
    create = await layered_client.post(
        "/api/v1/contacts",
        json={
            "full_name": "Asha Reddy",
            "phone": "+91 9000000001",
            "email": "asha@example.com",
            "source": "walk_in",
            "tags": ["lead", "vip"],
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["full_name"] == "Asha Reddy"
    assert body["custom_data"] == {}
    assert body["tags"] == ["lead", "vip"]
    contact_id = body["id"]

    # List
    listed = await layered_client.get("/api/v1/contacts", headers=headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["full_name"] == "Asha Reddy"

    # Get
    got = await layered_client.get(f"/api/v1/contacts/{contact_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["email"] == "asha@example.com"

    # Update (rename + replace tags)
    patch = await layered_client.patch(
        f"/api/v1/contacts/{contact_id}",
        json={"full_name": "Asha R.", "tags": ["vip"]},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["full_name"] == "Asha R."
    assert patch.json()["tags"] == ["vip"]

    # Delete
    delete = await layered_client.delete(
        f"/api/v1/contacts/{contact_id}", headers=headers
    )
    assert delete.status_code == 204

    # Confirm gone
    after = await layered_client.get(
        f"/api/v1/contacts/{contact_id}", headers=headers
    )
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_custom_data_unknown_key_rejected(layered_client, seeded_admin):
    """A custom_data key that has no `custom_field_definitions` row is 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/contacts",
        json={
            "full_name": "Test",
            "custom_data": {"not_defined_yet": "x"},
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "not defined" in resp.text


@pytest.mark.asyncio
async def test_custom_data_type_check_and_dob_accepted(
    layered_client, seeded_admin
):
    """A defined `dob` date field accepts ISO strings and rejects bad shapes."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    await _seed_field(org.id, field_key="dob", field_type=FieldType.date)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    good = await layered_client.post(
        "/api/v1/contacts",
        json={"full_name": "DOB OK", "custom_data": {"dob": "1990-05-01"}},
        headers=headers,
    )
    assert good.status_code == 201, good.text
    assert good.json()["custom_data"]["dob"] == "1990-05-01"

    bad = await layered_client.post(
        "/api/v1/contacts",
        json={"full_name": "DOB bad", "custom_data": {"dob": "not-a-date"}},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_required_custom_field_enforced_on_create(
    layered_client, seeded_admin
):
    """Required custom field absent on POST → 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    await _seed_field(
        org.id,
        field_key="loyalty_tier",
        field_type=FieldType.text,
        is_required=True,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    missing = await layered_client.post(
        "/api/v1/contacts",
        json={"full_name": "No tier"},
        headers=headers,
    )
    assert missing.status_code == 422, missing.text

    ok = await layered_client.post(
        "/api/v1/contacts",
        json={
            "full_name": "Has tier",
            "custom_data": {"loyalty_tier": "gold"},
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_rls_isolates_contacts_between_orgs(layered_client, seeded_admin):
    """A row inserted under org A must not appear when org B lists contacts.

    Both contacts are created via the API as org B's admin (no perms
    overlap) — this exercises the ORM `do_orm_execute` filter as well
    as the RLS policy on the table.
    """
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")

    # Insert a contact for a *different* org directly (RLS-aware insert).
    other_org_id = uuid.uuid4()
    other_token = set_context(RequestContext(org_id=other_org_id))
    try:
        # We need the org row first to satisfy the FK.
        from src.app.core.tenants.models import Organization

        async with TestSession() as session:
            session.add(
                Organization(
                    id=other_org_id,
                    name="Other",
                    slug=f"other-{other_org_id.hex[:6]}",
                )
            )
            await session.flush()
            session.add(
                Contact(
                    org_id=other_org_id,
                    full_name="Other Org Contact",
                    custom_data={},
                    tags=[],
                )
            )
            await session.commit()
    finally:
        reset_context(other_token)

    token = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get("/api/v1/contacts", headers=headers)
    assert resp.status_code == 200
    names = [item["full_name"] for item in resp.json()["items"]]
    assert "Other Org Contact" not in names


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    """A user without `contacts.write` is 403 on POST."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/contacts",
        json={"full_name": "X"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
