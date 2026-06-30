"""HTTP coverage for walk-ins convert + bulk endpoints (Step 3).

Five cases:

  1. `POST /walk-ins/{id}/convert` with `contact_link_mode=auto` →
     creates a lead, stamps `walk_in.linked_lead_id`, writes a
     `convert` activity.
  2. Convert when `linked_lead_id` is already set → 409 "already
     converted" with the existing lead id in the response.
  3. Convert with `mode=link` and a cross-tenant `linked_contact_id`
     → 422 (the contact isn't visible in this org's RLS scope).
  4. `POST /walk-ins/bulk-reassign` over three walk-ins writes three
     `reassign` activities and updates every row's owner.
  5. `POST /walk-ins/bulk-checkout` mixing open + already-checked-out
     visits returns the partial-success split
     `{"checked_out": N, "already_checked_out": M}`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
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


async def _seed_leads_pipeline(org_id: uuid.UUID) -> None:
    """Convert creates a lead via leads.service which needs a default
    pipeline stage — seed the canonical `leads` pipeline."""
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


async def _seed_contact(org_id: uuid.UUID, *, phone: str = "+91 9000000001") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name="Walk-in tester",
                phone=phone,
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_walkin(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    status: WalkInStatus = WalkInStatus.browsing,
    time_out: datetime | None = None,
    linked_lead_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            w = WalkIn(
                org_id=org_id,
                contact_id=contact_id,
                status=status,
                time_out=time_out,
                linked_lead_id=linked_lead_id,
            )
            session.add(w)
            await session.commit()
            return w.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_convert_auto_creates_lead_and_links_walkin(layered_client, seeded_admin):
    """Happy path. `auto` reuses the walk-in's existing contact; the
    new lead lands at the first stage of the `leads` pipeline; the
    walk-in's `linked_lead_id` is stamped; a `convert` activity is
    written on the walk-in's timeline."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "walkins.read",
        "walkins.write",
        "leads.read",
        "leads.write",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    walk_in_id = await _seed_walkin(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/walk-ins/{walk_in_id}/convert",
        json={"contact_link_mode": "auto", "notes": "serious buyer"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["walk_in_id"] == str(walk_in_id)
    assert body["contact_id"] == str(contact_id)
    lead_id = uuid.UUID(body["lead_id"])

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(WalkIn).where(WalkIn.id == walk_in_id))
            ).scalar_one()
            assert row.linked_lead_id == lead_id

            activities = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "walk_in")
                        .where(Activity.entity_id == walk_in_id)
                        .where(Activity.type == ActivityType.convert)
                    )
                )
                .scalars()
                .all()
            )
            assert len(activities) == 1
            payload = activities[0].payload
            assert payload["lead_id"] == str(lead_id)
            assert payload["contact_id"] == str(contact_id)
            assert payload["notes"] == "serious buyer"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_convert_already_linked_returns_409(layered_client, seeded_admin):
    """A walk-in already converted (linked_lead_id set) re-converts to
    409. The response embeds the existing lead id so the FE can
    redirect without re-issuing the call."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "walkins.read",
        "walkins.write",
        "leads.read",
        "leads.write",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    existing_lead = uuid.uuid4()
    walk_in_id = await _seed_walkin(org.id, contact_id=contact_id, linked_lead_id=existing_lead)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/walk-ins/{walk_in_id}/convert",
        json={"contact_link_mode": "auto"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["lead_id"] == str(existing_lead)


@pytest.mark.asyncio
async def test_convert_link_mode_cross_tenant_contact_rejected(layered_client, seeded_admin):
    """`mode=link` with a `linked_contact_id` not in this org's scope
    → 422. The ORM-level tenant filter makes the unknown contact
    invisible to the in-scope lookup, so the service raises the
    "contact not in this org" guard."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "walkins.read",
        "walkins.write",
        "leads.read",
        "leads.write",
    )
    await _seed_leads_pipeline(org.id)
    contact_id = await _seed_contact(org.id)
    walk_in_id = await _seed_walkin(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/walk-ins/{walk_in_id}/convert",
        json={
            "contact_link_mode": "link",
            "linked_contact_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_bulk_reassign_writes_activity_per_row(layered_client, seeded_admin):
    """Bulk reassign over three walk-ins updates every row's owner
    and emits one `reassign` activity per row."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "walkins.read",
        "walkins.write",
        "walkins.reassign",
    )
    contact_id = await _seed_contact(org.id)
    ids = [await _seed_walkin(org.id, contact_id=contact_id) for _ in range(3)]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/walk-ins/bulk-reassign",
        json={
            "ids": [str(i) for i in ids],
            "assigned_to_id": str(user.legacy_uuid),
            "note": "shift handover",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reassigned"] == 3

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            for wid in ids:
                row = (await session.execute(select(WalkIn).where(WalkIn.id == wid))).scalar_one()
                assert row.assigned_to_id == user.legacy_uuid

            activities = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "walk_in")
                        .where(Activity.entity_id.in_(ids))
                        .where(Activity.type == ActivityType.reassign)
                    )
                )
                .scalars()
                .all()
            )
            assert len(activities) == 3
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_checkout_partial_success_with_already_checked_out(layered_client, seeded_admin):
    """Mixing open + already-checked-out walk-ins should NOT error.
    The response splits the count: `checked_out` for rows newly
    stamped, `already_checked_out` for rows skipped. Same semantic
    as the single-row endpoint."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)

    open_a = await _seed_walkin(org.id, contact_id=contact_id)
    open_b = await _seed_walkin(org.id, contact_id=contact_id)
    closed = await _seed_walkin(
        org.id,
        contact_id=contact_id,
        time_out=datetime.now(UTC),
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/walk-ins/bulk-checkout",
        json={"ids": [str(open_a), str(open_b), str(closed)]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checked_out"] == 2
    assert body["already_checked_out"] == 1
