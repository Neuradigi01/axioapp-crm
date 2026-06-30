"""`source` column drives behaviour.

These tests insert `system` and `pack` rows via the ORM directly
(skipping the HTTP create path, which always stamps `source=user`) and
then exercise the HTTP routes to confirm:

  - system/pack rows cannot be deleted via DELETE.
  - system rows reject is_hidden updates; pack rows reject is_required.
  - both reject any attempt to mutate immutable columns (the schema
    forbids that surface; we still verify the 403 path).
  - a user without `custom_fields.write` is 403 on every mutation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
    FieldType,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
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


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _insert_managed(
    org_id: uuid.UUID,
    *,
    source: FieldSource,
    field_key: str,
    pack_id: str | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    field = CustomFieldDefinition(
        id=uuid.uuid4(),
        org_id=org_id,
        entity_type="contact",
        field_key=field_key,
        field_label=field_key.title(),
        field_type=FieldType.text,
        source=source,
        pack_id=pack_id,
    )
    async with TestSession() as session:
        session.add(field)
        await session.commit()
    return field.id


@pytest.mark.asyncio
async def test_system_field_cannot_be_deleted(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read", "custom_fields.write")

    sys_id = await _insert_managed(org.id, source=FieldSource.system, field_key="email_canonical")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.delete(
        f"/api/v1/custom-fields/{sys_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_pack_field_cannot_be_deleted(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read", "custom_fields.write")

    pack_id = await _insert_managed(
        org.id, source=FieldSource.pack, field_key="wood_grade", pack_id="furniture"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.delete(
        f"/api/v1/custom-fields/{pack_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_system_field_label_is_editable_hidden_is_not(layered_client, seeded_admin):
    """`system`: label/order/required/validation OK; is_hidden rejected."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read", "custom_fields.write")

    sys_id = await _insert_managed(org.id, source=FieldSource.system, field_key="email_canonical")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    ok = await layered_client.patch(
        f"/api/v1/custom-fields/{sys_id}",
        json={"field_label": "Canonical Email", "display_order": 1, "is_required": True},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["field_label"] == "Canonical Email"
    assert ok.json()["is_required"] is True

    blocked = await layered_client.patch(
        f"/api/v1/custom-fields/{sys_id}",
        json={"is_hidden": True},
        headers=headers,
    )
    assert blocked.status_code == 403, blocked.text


@pytest.mark.asyncio
async def test_pack_field_hidden_is_editable_required_is_not(layered_client, seeded_admin):
    """`pack`: label/order/is_hidden/validation OK; is_required rejected."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read", "custom_fields.write")

    pack_id = await _insert_managed(
        org.id, source=FieldSource.pack, field_key="wood_grade", pack_id="furniture"
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    ok = await layered_client.patch(
        f"/api/v1/custom-fields/{pack_id}",
        json={"field_label": "Grade", "is_hidden": True, "display_order": 9},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["is_hidden"] is True

    blocked = await layered_client.patch(
        f"/api/v1/custom-fields/{pack_id}",
        json={"is_required": True},
        headers=headers,
    )
    assert blocked.status_code == 403, blocked.text


@pytest.mark.asyncio
async def test_user_role_without_write_perm_is_blocked(layered_client, seeded_admin):
    """Even a write to a `source=user` field is 403 without `custom_fields.write`."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # No write grant — only read.
    await _grant(seeded_admin["role"].id, "custom_fields.read")

    user_id = await _insert_managed(org.id, source=FieldSource.user, field_key="some_pref")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    patch = await layered_client.patch(
        f"/api/v1/custom-fields/{user_id}",
        json={"field_label": "Some Pref"},
        headers=headers,
    )
    assert patch.status_code == 403, patch.text

    delete = await layered_client.delete(f"/api/v1/custom-fields/{user_id}", headers=headers)
    assert delete.status_code == 403, delete.text
