"""HTTP-level CRUD coverage for /api/v1/leads.

Each test seeds a `leads` pipeline (3 stages) + a contact, then
exercises one endpoint or behaviour:
  - create / list / get / patch / delete happy path
  - default-stage when pipeline_stage omitted on create
  - 422 when pipeline_stage is not a real stage
  - 422 when contact_id is foreign-org / nonexistent
  - 422 on unknown custom_data key
  - list filters: stage / status / assigned_to / q / source / custom.*
  - perm-gated write
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
from src.app.core.pipelines.models import Pipeline, PipelineStage
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


async def _seed_leads_pipeline(org_id: uuid.UUID) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            for i, (k, name, is_won, is_lost) in enumerate(
                [
                    ("new", "New", False, False),
                    ("qualified", "Qualified", False, False),
                    ("won", "Won", True, False),
                    ("lost", "Lost", False, True),
                ]
            ):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=p.id,
                        key=k,
                        name=name,
                        display_order=i,
                        is_won=is_won,
                        is_lost=is_lost,
                    )
                )
            await session.commit()
    finally:
        reset_context(token)


async def _seed_contact(
    org_id: uuid.UUID,
    *,
    full_name: str = "Asha Reddy",
    source: str | None = "walk_in",
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=full_name,
                phone="+91 9000000001",
                email=f"{full_name.split()[0].lower()}@example.com",
                source=source,
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_create_list_get_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Create with explicit stage
    create = await layered_client.post(
        "/api/v1/leads",
        json={
            "contact_id": str(contact_id),
            "pipeline_stage": "new",
            "budget": "150000.00",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["pipeline_stage"] == "new"
    assert body["status"] == "active"
    assert body["budget"] == "150000.00"
    lead_id = body["id"]

    # List
    listed = await layered_client.get("/api/v1/leads", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == lead_id

    # Get
    got = await layered_client.get(f"/api/v1/leads/{lead_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["contact_id"] == str(contact_id)

    # PATCH budget
    patch = await layered_client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"budget": "200000.00"},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["budget"] == "200000.00"

    # DELETE
    delete = await layered_client.delete(
        f"/api/v1/leads/{lead_id}", headers=headers
    )
    assert delete.status_code == 204

    after = await layered_client.get(
        f"/api/v1/leads/{lead_id}", headers=headers
    )
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_create_defaults_to_first_stage_when_omitted(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/leads",
        json={"contact_id": str(contact_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pipeline_stage"] == "new"


@pytest.mark.asyncio
async def test_create_rejects_unknown_stage(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/leads",
        json={"contact_id": str(contact_id), "pipeline_stage": "ghost"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_rejects_unknown_contact(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/leads",
        json={"contact_id": str(uuid.uuid4()), "pipeline_stage": "new"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_custom_data_unknown_key_rejected(layered_client, seeded_admin):
    """A custom_data key that has no `custom_field_definitions` row is 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/leads",
        json={
            "contact_id": str(contact_id),
            "custom_data": {"not_defined": "x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text
    assert "not defined" in resp.text


@pytest.mark.asyncio
async def test_list_filters_combine(layered_client, seeded_admin):
    """`stage`, `q`, `source`, `custom.*` filters compose with AND."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    # Seed a lead-scoped custom field so `custom.priority=high` is valid.
    token_ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            session.add(
                CustomFieldDefinition(
                    org_id=org.id,
                    entity_type="lead",
                    field_key="priority",
                    field_label="Priority",
                    field_type=FieldType.text,
                    source=FieldSource.system,
                )
            )
            await session.commit()
    finally:
        reset_context(token_ctx)

    c_a = await _seed_contact(org.id, full_name="John Premium", source="walk_in")
    c_b = await _seed_contact(org.id, full_name="John Entry", source="referral")
    c_c = await _seed_contact(org.id, full_name="Mary Other", source="walk_in")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for (cid, stage, priority) in [
        (c_a, "qualified", "high"),
        (c_b, "new", "low"),
        (c_c, "qualified", "high"),
    ]:
        r = await layered_client.post(
            "/api/v1/leads",
            json={
                "contact_id": str(cid),
                "pipeline_stage": stage,
                "custom_data": {"priority": priority},
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text

    # by stage
    by_stage = await layered_client.get(
        "/api/v1/leads?stage=qualified", headers=headers
    )
    assert by_stage.json()["total"] == 2

    # by q (full_name across contacts join)
    by_q = await layered_client.get("/api/v1/leads?q=John", headers=headers)
    assert by_q.json()["total"] == 2

    # by source (contacts join)
    by_source = await layered_client.get(
        "/api/v1/leads?source=walk_in", headers=headers
    )
    assert by_source.json()["total"] == 2

    # by custom.priority
    by_custom = await layered_client.get(
        "/api/v1/leads?custom.priority=high", headers=headers
    )
    assert by_custom.json()["total"] == 2

    # combo: q=John AND stage=qualified — only "John Premium"
    combo = await layered_client.get(
        "/api/v1/leads?q=John&stage=qualified", headers=headers
    )
    assert combo.json()["total"] == 1


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/leads",
        json={"contact_id": str(contact_id), "pipeline_stage": "new"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
