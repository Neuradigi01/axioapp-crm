"""Coverage for `POST /api/v1/leads/{id}/move-stage`.

Asserts:
  - invalid `to_stage` rejected with 400 (pipeline engine's guard)
  - valid move updates `pipeline_stage` column AND writes audit + activity
  - moving to a won stage auto-syncs `status='won'`
  - moving to a lost stage auto-syncs `status='lost'`
  - moving back to a non-terminal stage resets `status='active'`
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity
from src.app.core.audit.models import AuditLog
from src.app.core.contacts.models import Contact
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


async def _seed_pipeline_and_contact(
    org_id: uuid.UUID,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            for i, (k, name, won, lost) in enumerate(
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
                        is_won=won,
                        is_lost=lost,
                    )
                )
            c = Contact(
                org_id=org_id,
                full_name="Move Tester",
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _create_lead(client, headers, contact_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/leads",
        json={"contact_id": str(contact_id), "pipeline_stage": "new"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_invalid_stage_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "ghost"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "not part of pipeline" in resp.text


@pytest.mark.asyncio
async def test_valid_move_writes_audit_and_activity(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "qualified"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pipeline_stage"] == "qualified"
    # Non-terminal destination — status stays active.
    assert body["status"] == "active"

    # Activity emitted
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            acts = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "leads")
                    .where(Activity.entity_id == uuid.UUID(lead_id))
                )
            ).scalars().all()
            assert len(acts) == 1
            assert acts[0].type.value == "status_change"
            assert acts[0].payload == {
                "pipeline": "leads",
                "from": "new",
                "to": "qualified",
            }

            ads = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "pipelines.card_moved")
                    .where(AuditLog.entity_id == uuid.UUID(lead_id))
                )
            ).scalars().all()
            assert len(ads) == 1
            assert ads[0].before == {"pipeline": "leads", "stage": "new"}
            assert ads[0].after == {"pipeline": "leads", "stage": "qualified"}
    finally:
        reset_context(ctx_token)


@pytest.mark.asyncio
async def test_move_to_won_sets_status_won(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "won"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["pipeline_stage"] == "won"
    assert resp.json()["status"] == "won"


@pytest.mark.asyncio
async def test_move_to_lost_sets_status_lost(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "lost"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "lost"


@pytest.mark.asyncio
async def test_move_back_resets_status_to_active(layered_client, seeded_admin):
    """won → qualified should reset status from won back to active."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    # First close it.
    won = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "won"},
        headers=headers,
    )
    assert won.json()["status"] == "won"

    # Then reopen.
    back = await layered_client.post(
        f"/api/v1/leads/{lead_id}/move-stage",
        json={"to_stage": "qualified"},
        headers=headers,
    )
    assert back.status_code == 200
    assert back.json()["status"] == "active"
    assert back.json()["pipeline_stage"] == "qualified"
