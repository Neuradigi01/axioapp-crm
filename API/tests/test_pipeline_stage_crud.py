"""HTTP coverage for the stage CRUD endpoints on the pipelines engine.

Exercises:

  POST   /api/v1/pipelines/{key}/stages
  DELETE /api/v1/pipelines/{key}/stages/{stage_id}

Both gated on `pipelines.manage`. POST slugifies `name` into a stable
stage key, rejects collisions and `is_won`/`is_lost` (extra='forbid'),
and shifts later stages' `display_order` when `after_stage_key` is
provided. DELETE refuses terminal stages, demands a relocation target
when cards exist in the stage being deleted, and UPDATE+DELETEs in one
transaction.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.audit.models import AuditLog
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.shared.context import RequestContext, reset_context, set_context

# Six-stage pipeline matching the task spec's POST happy-path scenario:
# inserting after "contacted" must shift qualified/proposal/won/lost up.
_STAGE_SPEC = [
    ("new", "New", False, False),
    ("contacted", "Contacted", False, False),
    ("qualified", "Qualified", False, False),
    ("proposal", "Proposal", False, False),
    ("won", "Won", True, False),
    ("lost", "Lost", False, True),
]


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


async def _seed_leads_pipeline(
    org_id: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """Insert the `leads` pipeline with 6 stages. Returns (pipeline_id, key→id)."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            ids: dict[str, uuid.UUID] = {}
            for i, (key, name, is_won, is_lost) in enumerate(_STAGE_SPEC):
                s = PipelineStage(
                    org_id=org_id,
                    pipeline_id=p.id,
                    key=key,
                    name=name,
                    display_order=i,
                    is_won=is_won,
                    is_lost=is_lost,
                )
                session.add(s)
                await session.flush()
                ids[key] = s.id
            await session.commit()
            return p.id, ids
    finally:
        reset_context(token)


async def _seed_contact(org_id: uuid.UUID, *, suffix: str) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=f"Buyer {suffix}",
                phone=f"+91 90000{suffix:>05}",
                email=f"buyer{suffix}@example.com",
                source="walk_in",
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_lead(org_id: uuid.UUID, *, contact_id: uuid.UUID, stage_key: str) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            lead = Lead(
                org_id=org_id,
                contact_id=contact_id,
                pipeline_stage=stage_key,
                status=LeadStatus.active,
            )
            session.add(lead)
            await session.commit()
            return lead.id
    finally:
        reset_context(token)


async def _stages_by_key(org_id: uuid.UUID) -> dict[str, PipelineStage]:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            rows = (await session.execute(select(PipelineStage))).scalars().all()
            return {s.key: s for s in rows}
    finally:
        reset_context(token)


# --- POST -------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_inserts_after_anchor_and_shifts_later_stages(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read", "pipelines.manage")
    await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/pipelines/leads/stages",
        json={"name": "Demo Scheduled", "after_stage_key": "contacted"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"] == "demo_scheduled"
    assert body["name"] == "Demo Scheduled"
    assert body["display_order"] == 2
    assert body["is_won"] is False
    assert body["is_lost"] is False

    listing = await layered_client.get("/api/v1/pipelines/leads", headers=headers)
    by_key = {s["key"]: s["display_order"] for s in listing.json()["stages"]}
    assert by_key == {
        "new": 0,
        "contacted": 1,
        "demo_scheduled": 2,
        "qualified": 3,
        "proposal": 4,
        "won": 5,
        "lost": 6,
    }


@pytest.mark.asyncio
async def test_post_appends_when_after_stage_key_omitted(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read", "pipelines.manage")
    await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/pipelines/leads/stages",
        json={"name": "Archived"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"] == "archived"
    assert body["display_order"] == len(_STAGE_SPEC)  # max(5) + 1


@pytest.mark.asyncio
async def test_post_key_collision_returns_422(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # "New" slugs to "new" — collides with the seeded "new" stage.
    resp = await layered_client.post(
        "/api/v1/pipelines/leads/stages",
        json={"name": "New"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_post_rejects_is_won_in_body(layered_client, seeded_admin):
    """`StageCreate` is extra='forbid' so callers can't sneak in is_won/is_lost."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for bad in ({"name": "Trophy", "is_won": True}, {"name": "Dead", "is_lost": True}):
        resp = await layered_client.post(
            "/api/v1/pipelines/leads/stages", json=bad, headers=headers
        )
        assert resp.status_code == 422, (bad, resp.text)


@pytest.mark.asyncio
async def test_post_without_manage_permission_is_403(layered_client, seeded_admin):
    """Employee-like caller with only `pipelines.read` cannot create stages."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read")
    await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/pipelines/leads/stages",
        json={"name": "Demo Scheduled", "after_stage_key": "contacted"},
        headers=headers,
    )
    assert resp.status_code == 403


# --- DELETE -----------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_empty_stage_succeeds(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['proposal']}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    stages = await _stages_by_key(org.id)
    assert "proposal" not in stages


@pytest.mark.asyncio
async def test_delete_stage_with_cards_without_target_is_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id, suffix="1")
    await _seed_lead(org.id, contact_id=contact_id, stage_key="qualified")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['qualified']}",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail == {"cards_in_stage": 1, "must_provide": "move_leads_to"}


@pytest.mark.asyncio
async def test_delete_stage_with_cards_relocates_then_deletes(layered_client, seeded_admin):
    """Cards in the deleted stage end up in the target; the stage row goes."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    c1 = await _seed_contact(org.id, suffix="1")
    c2 = await _seed_contact(org.id, suffix="2")
    l1 = await _seed_lead(org.id, contact_id=c1, stage_key="qualified")
    l2 = await _seed_lead(org.id, contact_id=c2, stage_key="qualified")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['qualified']}?move_leads_to=proposal",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    # Both leads moved to "proposal"; "qualified" stage gone.
    from tests.conftest import TestSession

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            leads = (
                (await session.execute(select(Lead).where(Lead.id.in_([l1, l2])))).scalars().all()
            )
            assert {l.pipeline_stage for l in leads} == {"proposal"}

            still_there = (
                await session.execute(
                    select(PipelineStage).where(PipelineStage.id == stage_ids["qualified"])
                )
            ).scalar_one_or_none()
            assert still_there is None
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_delete_won_stage_is_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Even with a relocation target supplied, won is undeletable.
    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['won']}?move_leads_to=new",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert "won/lost" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_lost_stage_is_409(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['lost']}", headers=headers
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_delete_without_manage_permission_is_403(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['proposal']}",
        headers=headers,
    )
    assert resp.status_code == 403


# --- Audit -----------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_rows_emitted_for_create_and_delete(layered_client, seeded_admin):
    """POST emits `pipelines.stage_created`; DELETE emits `pipelines.stage_deleted`
    carrying `cards_moved_count`."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id, suffix="1")
    await _seed_lead(org.id, contact_id=contact_id, stage_key="qualified")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await layered_client.post(
        "/api/v1/pipelines/leads/stages",
        json={"name": "Demo Scheduled", "after_stage_key": "contacted"},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    created_stage_id = uuid.UUID(create_resp.json()["id"])

    del_resp = await layered_client.delete(
        f"/api/v1/pipelines/leads/stages/{stage_ids['qualified']}?move_leads_to=proposal",
        headers=headers,
    )
    assert del_resp.status_code == 204, del_resp.text

    from tests.conftest import TestSession

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            created_rows = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "pipelines.stage_created")
                        .where(AuditLog.entity_id == created_stage_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(created_rows) == 1
            assert created_rows[0].after["key"] == "demo_scheduled"

            deleted_rows = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "pipelines.stage_deleted")
                        .where(AuditLog.entity_id == stage_ids["qualified"])
                    )
                )
                .scalars()
                .all()
            )
            assert len(deleted_rows) == 1
            after = deleted_rows[0].after
            assert after["cards_moved_count"] == 1
            assert after["cards_moved_to"] == "proposal"
            assert deleted_rows[0].before["key"] == "qualified"
    finally:
        reset_context(ctx)
