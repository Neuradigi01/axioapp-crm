"""HTTP coverage for the pipelines engine: read endpoints + stage PATCH.

Pipelines are normally created by the pack installer (Phase 4). For
test isolation we insert a small `leads` pipeline directly through the
TestSession bound to the tenant context.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Insert a `leads` pipeline with 3 stages. Returns (pipeline_id, stage_ids)."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            pipeline = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(pipeline)
            await session.flush()
            stages = [
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=pipeline.id,
                    key="new",
                    name="New",
                    color="#9ca3af",
                    display_order=0,
                ),
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=pipeline.id,
                    key="qualified",
                    name="Qualified",
                    color="#3b82f6",
                    display_order=1,
                ),
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=pipeline.id,
                    key="won",
                    name="Won",
                    color="#10b981",
                    display_order=2,
                    is_won=True,
                ),
            ]
            for s in stages:
                session.add(s)
            await session.commit()
            return pipeline.id, [s.id for s in stages]
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_list_pipelines_is_initially_empty(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/pipelines", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_pipeline_by_key_returns_ordered_stages(layered_client, seeded_admin):
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
    resp = await layered_client.get(
        "/api/v1/pipelines/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == "leads"
    keys = [s["key"] for s in body["stages"]]
    assert keys == ["new", "qualified", "won"]
    assert body["stages"][2]["is_won"] is True


@pytest.mark.asyncio
async def test_patch_stage_label_color(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read", "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/pipelines/leads/stages/{stage_ids[1]}",
        json={"name": "Qualified Lead", "color": "#2563eb"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Qualified Lead"
    assert resp.json()["color"] == "#2563eb"


@pytest.mark.asyncio
async def test_patch_display_order_swaps_with_holder(layered_client, seeded_admin):
    """Moving stage[0] to slot 2 swaps stage[2] back to slot 0."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read", "pipelines.manage")
    _, stage_ids = await _seed_leads_pipeline(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Swap "new" (0) with "won" (2).
    resp = await layered_client.patch(
        f"/api/v1/pipelines/leads/stages/{stage_ids[0]}",
        json={"display_order": 2},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_order"] == 2

    listing = await layered_client.get("/api/v1/pipelines/leads", headers=headers)
    by_key = {s["key"]: s["display_order"] for s in listing.json()["stages"]}
    assert by_key == {"won": 0, "qualified": 1, "new": 2}


@pytest.mark.asyncio
async def test_patch_rejects_key_and_is_won_changes(layered_client, seeded_admin):
    """Schema has extra='forbid' so unknown / immutable keys fail with 422."""
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

    for bad_payload in (
        {"key": "renamed"},
        {"is_won": True},
        {"is_lost": True},
    ):
        resp = await layered_client.patch(
            f"/api/v1/pipelines/leads/stages/{stage_ids[1]}",
            json=bad_payload,
            headers=headers,
        )
        assert resp.status_code == 422, (bad_payload, resp.text)


@pytest.mark.asyncio
async def test_other_org_pipeline_invisible(layered_client, seeded_admin):
    """RLS: an admin in org A cannot see org B's leads pipeline."""
    from src.app.core.tenants.models import Organization
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "pipelines.read")

    org_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_b_id,
                name="OtherP",
                slug=f"otherp-{org_b_id.hex[:6]}",
            )
        )
        await session.commit()

    await _seed_leads_pipeline(org_b_id)
    token = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    listing = await layered_client.get("/api/v1/pipelines", headers=headers)
    assert listing.status_code == 200
    assert listing.json() == []

    one = await layered_client.get("/api/v1/pipelines/leads", headers=headers)
    assert one.status_code == 404
