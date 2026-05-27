"""HTTP-level coverage for leads reassign + bulk endpoints.

Five cases — mirrors `test_contacts_reassign_and_bulk.py` for the leads
entity:

  1. `POST /leads/{id}/reassign` writes new owner + audit activity +
     bumps `last_activity_at`.
  2. `POST /leads/bulk-reassign` updates N rows + writes N audit
     activities.
  3. `POST /leads/bulk-delete` removes N rows.
  4. Cross-tenant target user → 422.
  5. Caller without `leads.reassign` → 403.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadSource, LeadStatus
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
            session.add(
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=p.id,
                    key="new",
                    name="New",
                    display_order=0,
                )
            )
            await session.commit()
    finally:
        reset_context(token)


async def _seed_contact(org_id: uuid.UUID) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name="Asha",
                phone="+91 9000000001",
                email="asha@example.com",
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_lead(org_id: uuid.UUID, contact_id: uuid.UUID) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            lead = Lead(
                org_id=org_id,
                contact_id=contact_id,
                pipeline_stage="new",
                status=LeadStatus.active,
                source=LeadSource.manual,
            )
            session.add(lead)
            await session.commit()
            return lead.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_reassign_writes_owner_activity_and_bumps_last_activity(
    layered_client, seeded_admin
):
    """One endpoint hit covers test cases 1-3 (owner + activity + bump)."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.reassign",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/reassign",
        json={"assigned_to_id": str(user.legacy_uuid), "note": "transfer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assigned_to_id"] == str(user.legacy_uuid)

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Lead).where(Lead.id == lead_id))
            ).scalar_one()
            assert row.assigned_to_id == user.legacy_uuid
            assert row.last_activity_at is not None  # bumped by hook

            activities = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "lead")
                    .where(Activity.entity_id == lead_id)
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(activities) == 1
            payload = activities[0].payload
            assert payload["to"] == str(user.legacy_uuid)
            assert payload["note"] == "transfer"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_reassign_updates_all_and_writes_activities(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.reassign",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    ids = [await _seed_lead(org.id, contact_id) for _ in range(3)]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/leads/bulk-reassign",
        json={
            "ids": [str(i) for i in ids],
            "assigned_to_id": str(user.legacy_uuid),
            "note": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reassigned"] == 3

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            for lid in ids:
                row = (
                    await session.execute(select(Lead).where(Lead.id == lid))
                ).scalar_one()
                assert row.assigned_to_id == user.legacy_uuid

            count = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "lead")
                    .where(Activity.entity_id.in_(ids))
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(count) == 3
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_delete_removes_rows(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    ids = [await _seed_lead(org.id, contact_id) for _ in range(2)]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/leads/bulk-delete",
        json={"ids": [str(i) for i in ids]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 2

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            remaining = (
                await session.execute(
                    select(Lead).where(Lead.id.in_(ids))
                )
            ).scalars().all()
            assert remaining == []
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_reassign_cross_tenant_target_rejected(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.reassign",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/reassign",
        json={"assigned_to_id": str(uuid.uuid4()), "note": None},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_reassign_without_permission_returns_403(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Deliberately omit `leads.reassign`.
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/reassign",
        json={"assigned_to_id": str(user.legacy_uuid), "note": None},
        headers=headers,
    )
    assert resp.status_code == 403
