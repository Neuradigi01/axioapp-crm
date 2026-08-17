"""Coverage for the Leads Center toolbar's backend surface:

1. ``created_from`` inclusive
2. ``created_to`` inclusive end-of-day
3. combined bounds
4. missing bound → unbounded
5. ``sort=next_follow_up_due&order=asc`` — earliest first, NULLS LAST
6. same sort, ``order=desc`` — NULLS still last
7. ``with_unfiltered_total`` returns the tenant-wide count alongside
   the filtered ``total``
8. CSV Excel-safety on free-text cells (formula prefix → apostrophe)
9. CSV Excel-safety on custom-field cells
10. Filter DSL ``{"created_at":{"gte":...}}`` still works alongside
    the new convenience params
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.tasks.models import Task, TaskFollowupType, TaskStatus
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


async def _seed_pipeline(org_id: uuid.UUID) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            for i, k in enumerate(("new", "qualified", "won", "lost")):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=p.id,
                        key=k,
                        name=k.title(),
                        display_order=i,
                        is_won=(k == "won"),
                        is_lost=(k == "lost"),
                    )
                )
            await session.commit()
    finally:
        reset_context(token)


async def _seed_lead_with_created_at(
    org_id: uuid.UUID, *, name: str, created_at: datetime, status: LeadStatus = LeadStatus.active
) -> uuid.UUID:
    """Insert a lead + contact and force ``created_at`` to a specific
    moment (bypassing the server_default). Returns the lead id."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(org_id=org_id, full_name=name, custom_data={}, tags=[])
            session.add(c)
            await session.flush()
            lead = Lead(
                org_id=org_id,
                contact_id=c.id,
                pipeline_stage="new",
                status=status,
                custom_data={},
            )
            session.add(lead)
            await session.flush()
            await session.execute(
                text("UPDATE tbl_leads SET created_at = :ts WHERE id = :id"),
                {"ts": created_at, "id": lead.id},
            )
            await session.commit()
            return lead.id
    finally:
        reset_context(token)


async def _seed_open_task_for_lead(
    org_id: uuid.UUID, *, lead_id: uuid.UUID, due_at: datetime, assignee: uuid.UUID
) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            session.add(
                Task(
                    org_id=org_id,
                    title=f"Follow up {lead_id}",
                    due_at=due_at,
                    assigned_to_id=assignee,
                    related_entity_type="lead",
                    related_entity_id=lead_id,
                    status=TaskStatus.open,
                    followup_type=TaskFollowupType.call,
                )
            )
            await session.commit()
    finally:
        reset_context(token)


# --- 1-4. created_from / created_to bounds ---------------------------------


@pytest.mark.asyncio
async def test_created_from_inclusive(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 15, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 16, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="C", created_at=datetime(2026, 8, 17, 12, tzinfo=UTC)
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r1 = await layered_client.get(
        "/api/v1/leads?created_from=2026-08-16&sort=created_at&order=asc", headers=headers
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["total"] == 2

    r2 = await layered_client.get(
        "/api/v1/leads?created_from=2026-08-17&sort=created_at&order=asc", headers=headers
    )
    assert r2.json()["total"] == 1


@pytest.mark.asyncio
async def test_created_to_inclusive_end_of_day(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    # A at start-of-day, B late-evening — both must be inside `created_to=2026-08-16`.
    await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 15, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 16, 23, 59, 59, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="C", created_at=datetime(2026, 8, 17, 0, 30, tzinfo=UTC)
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get("/api/v1/leads?created_to=2026-08-16", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_created_from_and_to_combined(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 15, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 16, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="C", created_at=datetime(2026, 8, 17, 12, tzinfo=UTC)
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get(
        "/api/v1/leads?created_from=2026-08-16&created_to=2026-08-16", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


# --- 5-6. next_follow_up_due sort ------------------------------------------


@pytest.mark.asyncio
async def test_sort_next_follow_up_due_asc_nulls_last(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    a = await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 1, 10, tzinfo=UTC)
    )
    b = await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 2, 10, tzinfo=UTC)
    )
    c = await _seed_lead_with_created_at(
        org.id, name="C", created_at=datetime(2026, 8, 3, 10, tzinfo=UTC)
    )

    # A: due tomorrow+3, B: due tomorrow+1, C: no open task.
    now = datetime.now(UTC)
    await _seed_open_task_for_lead(
        org.id, lead_id=a, due_at=now + timedelta(days=3), assignee=user.legacy_uuid
    )
    await _seed_open_task_for_lead(
        org.id, lead_id=b, due_at=now + timedelta(days=1), assignee=user.legacy_uuid
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get("/api/v1/leads?sort=next_follow_up_due&order=asc", headers=headers)
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()["items"]]
    assert ids == [str(b), str(a), str(c)]


@pytest.mark.asyncio
async def test_sort_next_follow_up_due_desc_nulls_still_last(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    a = await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 1, 10, tzinfo=UTC)
    )
    b = await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 2, 10, tzinfo=UTC)
    )
    c = await _seed_lead_with_created_at(
        org.id, name="C", created_at=datetime(2026, 8, 3, 10, tzinfo=UTC)
    )

    now = datetime.now(UTC)
    await _seed_open_task_for_lead(
        org.id, lead_id=a, due_at=now + timedelta(days=3), assignee=user.legacy_uuid
    )
    await _seed_open_task_for_lead(
        org.id, lead_id=b, due_at=now + timedelta(days=1), assignee=user.legacy_uuid
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get(
        "/api/v1/leads?sort=next_follow_up_due&order=desc", headers=headers
    )
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()["items"]]
    # A furthest-out first, B next, C (no task) still last — NULLS LAST invariant.
    assert ids == [str(a), str(b), str(c)]


# --- 7. unfiltered_total ---------------------------------------------------


@pytest.mark.asyncio
async def test_unfiltered_total_alongside_filtered_total(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)

    # 5 leads: 2 won, 3 active.
    for i in range(2):
        await _seed_lead_with_created_at(
            org.id,
            name=f"W{i}",
            created_at=datetime(2026, 8, 10 + i, tzinfo=UTC),
            status=LeadStatus.won,
        )
    for i in range(3):
        await _seed_lead_with_created_at(
            org.id,
            name=f"A{i}",
            created_at=datetime(2026, 8, 12 + i, tzinfo=UTC),
            status=LeadStatus.active,
        )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get(
        "/api/v1/leads?status=won&with_unfiltered_total=true", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["unfiltered_total"] == 5

    # Opt-out: without the flag, unfiltered_total stays null.
    r2 = await layered_client.get("/api/v1/leads?status=won", headers=headers)
    assert r2.json().get("unfiltered_total") is None


# --- 8-9. CSV Excel-safety -------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_escapes_formula_in_name(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "leads.export")
    await _seed_pipeline(org.id)
    await _seed_lead_with_created_at(
        org.id,
        name="=cmd|calc",
        created_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get("/api/v1/leads/export.csv", headers=headers)
    assert r.status_code == 200, r.text
    body = r.text
    # Cell rendered as `'=cmd|calc` (the leading apostrophe forces text).
    assert "'=cmd|calc" in body


@pytest.mark.asyncio
async def test_csv_export_escapes_formula_in_custom_field(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "leads.export")
    await _seed_pipeline(org.id)
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            session.add(
                CustomFieldDefinition(
                    org_id=org.id,
                    entity_type="lead",
                    field_key="segment",
                    label="Segment",
                    kind="text",
                    source="user",
                )
            )
            await session.commit()
    finally:
        reset_context(ctx_token)

    # Seed a lead with the poisoned custom-field value.
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            c = Contact(org_id=org.id, full_name="Cust", custom_data={}, tags=[])
            session.add(c)
            await session.flush()
            session.add(
                Lead(
                    org_id=org.id,
                    contact_id=c.id,
                    pipeline_stage="new",
                    status=LeadStatus.active,
                    custom_data={"segment": "+leaked"},
                )
            )
            await session.commit()
    finally:
        reset_context(ctx_token)

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    r = await layered_client.get("/api/v1/leads/export.csv", headers=headers)
    assert r.status_code == 200
    assert "'+leaked" in r.text


# --- 10. DSL still works ---------------------------------------------------


@pytest.mark.asyncio
async def test_filter_dsl_created_at_still_works(layered_client, seeded_admin):
    """The new ``created_from`` convenience param does not obviate the
    existing DSL surface — both must produce the same result set."""
    import json as _json
    from urllib.parse import quote

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_pipeline(org.id)
    await _seed_lead_with_created_at(
        org.id, name="A", created_at=datetime(2026, 8, 15, 12, tzinfo=UTC)
    )
    await _seed_lead_with_created_at(
        org.id, name="B", created_at=datetime(2026, 8, 17, 12, tzinfo=UTC)
    )

    token = await _login(
        layered_client, org_slug=org.slug, email=user.email, password=seeded_admin["password"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    convenience = await layered_client.get("/api/v1/leads?created_from=2026-08-16", headers=headers)
    assert convenience.status_code == 200
    dsl_body = quote(_json.dumps({"created_at": {"gte": "2026-08-16"}}))
    dsl = await layered_client.get(f"/api/v1/leads?filter={dsl_body}", headers=headers)
    assert dsl.status_code == 200

    assert convenience.json()["total"] == dsl.json()["total"] == 1
