"""HTTP-level coverage for the leads `last_activity_at` + Lost-reason
features introduced in `update-leads-page/` Step 1.

Cases:

  1. Activity-insert on a lead bumps `last_activity_at` (the dispatch
     dict was extended in this step).
  2. `list?sort=last_activity_at&order=desc` returns leads
     newest-first with NULLs at the bottom.
  3. `list?last_activity_lt=<ts>` returns leads gone cold (NULL is
     treated as "very old" so never-touched leads surface in the
     "no activity in N days" chip).
  4. `list?sort=evil` → 422 (server-side whitelist).
  5. `PATCH /leads/{id}` with `lost_reason='evil'` → 422.
  6. `PATCH /leads/{id}` with `lost_reason='other'` and no
     `lost_reason_other` → 422.
  7. `PATCH /leads/{id}` with `lost_reason='timing'` → 200; field
     persisted.
  8. `move-stage` to a Lost stage without `lost_reason` → 422.
  9. `move-stage` to a Lost stage with valid `lost_reason` → 200;
     `lost_reason` + `status` persisted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import ActivityType
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


async def _seed_contact(org_id: uuid.UUID, *, full_name: str = "Asha") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=full_name,
                phone="+91 9000000001",
                email=f"{full_name.split()[0].lower()}@example.com",
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_lead(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    pipeline_stage: str = "new",
    last_activity_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            lead = Lead(
                org_id=org_id,
                contact_id=contact_id,
                pipeline_stage=pipeline_stage,
                status=LeadStatus.active,
                source=LeadSource.manual,
                last_activity_at=last_activity_at,
            )
            session.add(lead)
            await session.commit()
            return lead.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_activity_insert_bumps_lead_last_activity_at(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "activities.read",
        "activities.write",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/activities",
        json={
            "entity_type": "lead",
            "entity_id": str(lead_id),
            "type": "note",
            "payload": {"text": "first call"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Lead).where(Lead.id == lead_id))
            ).scalar_one()
            assert row.last_activity_at is not None
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_list_sort_by_last_activity_desc_nulls_last(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    now = datetime.now(timezone.utc)
    older = await _seed_lead(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(hours=3),
    )
    newer = await _seed_lead(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(minutes=15),
    )
    never = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        "/api/v1/leads?sort=last_activity_at&order=desc", headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = [it["id"] for it in resp.json()["items"]]
    assert ids == [str(newer), str(older), str(never)]


@pytest.mark.asyncio
async def test_list_last_activity_lt_includes_nulls(
    layered_client, seeded_admin
):
    """`?last_activity_lt=<ts>` returns rows older than ts OR with NULL —
    never-touched leads surface in the no-activity chip."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    stale = await _seed_lead(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(days=10),
    )
    fresh = await _seed_lead(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(hours=2),
    )
    never = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        f"/api/v1/leads?last_activity_lt={cutoff.isoformat()}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {it["id"] for it in resp.json()["items"]}
    assert str(stale) in ids
    assert str(never) in ids
    assert str(fresh) not in ids


@pytest.mark.asyncio
async def test_list_rejects_unknown_sort_key(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    bad = await layered_client.get(
        "/api/v1/leads?sort=evil", headers=headers
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_patch_rejects_unknown_lost_reason(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"lost_reason": "evil"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_lost_reason_other_requires_text(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"lost_reason": "other"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_patch_valid_lost_reason_persists(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"lost_reason": "timing"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lost_reason"] == "timing"


@pytest.mark.asyncio
async def test_move_stage_to_lost_requires_reason(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "lost"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_move_stage_to_lost_with_reason_persists(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    lead_id = await _seed_lead(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "lost", "lost_reason": "competitor"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "lost"
    assert body["pipeline_stage"] == "lost"
    assert body["lost_reason"] == "competitor"
