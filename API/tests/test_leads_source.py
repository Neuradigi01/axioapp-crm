"""Coverage for the `lead.source` provenance column (Step 1 of the
manual-lead-entry track).

Pins:
  - LeadSource enum membership (catches accidental rename / deletion).
  - HTTP default applied when caller omits `source`.
  - Explicit source values accepted across all five channels.
  - Invalid source values rejected by Pydantic (422).
  - DB-level NOT NULL on `source`.
  - Audit row `leads.created` includes `source` in its `after` snapshot
    (the contract every later channel reuses).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from src.app.core.audit.models import AuditLog
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadSource
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
                    is_won=False,
                    is_lost=False,
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
                full_name="Asha Reddy",
                phone="+91 9000000001",
                email="asha@example.com",
                source="walk_in",
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


def test_enum_membership() -> None:
    assert {m.value for m in LeadSource} == {
        "manual",
        "bulk_import",
        "widget",
        "google_ads",
        "meta_ads",
    }


@pytest.mark.asyncio
async def test_create_defaults_source_to_manual(layered_client, seeded_admin):
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
    assert resp.json()["source"] == "manual"


@pytest.mark.asyncio
async def test_create_accepts_explicit_source(layered_client, seeded_admin):
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

    for value in ("manual", "bulk_import", "widget", "google_ads", "meta_ads"):
        # Each call needs a fresh contact to satisfy the row's own constraints
        # (none in our schema strictly require it, but stays close to reality).
        resp = await layered_client.post(
            "/api/v1/leads",
            json={"contact_id": str(contact_id), "source": value},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["source"] == value


@pytest.mark.asyncio
async def test_create_rejects_invalid_source(layered_client, seeded_admin):
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
        json={"contact_id": str(contact_id), "source": "facebook"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_audit_log_records_source(layered_client, seeded_admin):
    """`leads.created` audit rows must carry `source` in `after`.

    Every later ingestion channel (bulk-import, widget, ads) reuses this
    event shape; the test pins the contract.
    """
    from tests.conftest import TestSession

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
        json={"contact_id": str(contact_id), "source": "widget"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    lead_id = resp.json()["id"]

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            rows = (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "leads.created")
                    .where(AuditLog.entity_id == uuid.UUID(lead_id))
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].after is not None
            assert rows[0].after.get("source") == "widget"
    finally:
        reset_context(ctx_token)


@pytest.mark.asyncio
async def test_db_level_not_null_on_source(seeded_admin):
    """Direct SQL insert without `source` violates NOT NULL.

    Guards against a future regression where the model/migration drift
    apart on the constraint.
    """
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    # Need a contact to satisfy the FK.
    contact_id = await _seed_contact(org.id)

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO tbl_leads "
                        "(org_id, contact_id, pipeline_stage, source) "
                        "VALUES (:org, :contact, 'new', NULL)"
                    ),
                    {"org": org.id, "contact": contact_id},
                )
                await session.commit()
    finally:
        reset_context(ctx_token)
