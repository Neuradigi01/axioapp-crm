"""Search & filter coverage for /api/v1/contacts.

Verifies the `q`, `source`, `tag`, and `custom.<key>=<value>` filters
each narrow the result set as documented, and that combining them
applies AND semantics.
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


async def _create(client, headers, **payload) -> str:
    resp = await client.post("/api/v1/contacts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_search_by_q_source_tag_and_custom_field(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    await _seed_field(
        org.id,
        field_key="budget_range",
        field_type=FieldType.select,
        options={"choices": ["entry", "mid", "premium"]},
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await _create(
        layered_client,
        headers,
        full_name="John Premium",
        source="walk_in",
        tags=["lead"],
        custom_data={"budget_range": "premium"},
    )
    await _create(
        layered_client,
        headers,
        full_name="John Entry",
        source="referral",
        tags=["lead", "cold"],
        custom_data={"budget_range": "entry"},
    )
    await _create(
        layered_client,
        headers,
        full_name="Mary Other",
        source="walk_in",
        tags=["cold"],
        custom_data={"budget_range": "premium"},
    )

    # q narrows by full_name
    by_q = await layered_client.get(
        "/api/v1/contacts?q=John", headers=headers
    )
    assert by_q.status_code == 200
    names = {i["full_name"] for i in by_q.json()["items"]}
    assert names == {"John Premium", "John Entry"}

    # source narrows
    by_source = await layered_client.get(
        "/api/v1/contacts?source=referral", headers=headers
    )
    assert {i["full_name"] for i in by_source.json()["items"]} == {"John Entry"}

    # tag narrows
    by_tag = await layered_client.get(
        "/api/v1/contacts?tag=cold", headers=headers
    )
    assert {i["full_name"] for i in by_tag.json()["items"]} == {
        "John Entry",
        "Mary Other",
    }

    # custom-field filter
    by_custom = await layered_client.get(
        "/api/v1/contacts?custom.budget_range=premium", headers=headers
    )
    assert {i["full_name"] for i in by_custom.json()["items"]} == {
        "John Premium",
        "Mary Other",
    }

    # AND of q + custom-field — the master prompt's example
    combo = await layered_client.get(
        "/api/v1/contacts?q=John&custom.budget_range=premium",
        headers=headers,
    )
    assert combo.status_code == 200
    items = combo.json()["items"]
    assert [i["full_name"] for i in items] == ["John Premium"]
    assert combo.json()["total"] == 1


@pytest.mark.asyncio
async def test_q_matches_phone_and_email_too(layered_client, seeded_admin):
    """`q` is an ILIKE across full_name, phone, and email."""
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

    await _create(
        layered_client,
        headers,
        full_name="No-Match Name",
        phone="+91 99999 12345",
    )
    await _create(
        layered_client,
        headers,
        full_name="Other",
        email="bigboss@store.local",
    )

    by_phone = await layered_client.get(
        "/api/v1/contacts?q=12345", headers=headers
    )
    assert {i["full_name"] for i in by_phone.json()["items"]} == {"No-Match Name"}

    by_email = await layered_client.get(
        "/api/v1/contacts?q=bigboss", headers=headers
    )
    assert {i["full_name"] for i in by_email.json()["items"]} == {"Other"}


@pytest.mark.asyncio
async def test_pagination_total_and_page_size(layered_client, seeded_admin):
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

    for n in range(7):
        await _create(layered_client, headers, full_name=f"P{n}")

    page1 = await layered_client.get(
        "/api/v1/contacts?page=1&size=3", headers=headers
    )
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 7
    assert body["page"] == 1
    assert body["size"] == 3
    assert len(body["items"]) == 3

    page3 = await layered_client.get(
        "/api/v1/contacts?page=3&size=3", headers=headers
    )
    assert len(page3.json()["items"]) == 1
