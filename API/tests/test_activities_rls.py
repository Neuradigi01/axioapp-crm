"""Tenant-isolation coverage for activities.

Inserts a row under org B (via the internal `log` helper bound to
org B's RequestContext) and verifies it's invisible to org A's HTTP
reader. Covers both layers of isolation: the ORM `do_orm_execute`
filter on `TenantScoped` and the Postgres RLS policy on `activities`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities import log
from src.app.core.activities.models import Activity, ActivityType
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tenants.models import Organization
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


@pytest.mark.asyncio
async def test_other_org_activities_invisible(layered_client, seeded_admin):
    """An activity logged under org B does not appear in org A's list."""
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")

    # Create a sibling org B and stash an activity under it via log().
    org_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_b_id,
                name="Other",
                slug=f"other-{org_b_id.hex[:6]}",
            )
        )
        await session.commit()

    shared_entity = uuid.uuid4()
    ctx_token = set_context(RequestContext(org_id=org_b_id))
    try:
        await log(
            entity_type="contact",
            entity_id=shared_entity,
            type=ActivityType.note,
            payload={"text": "org B internal"},
        )
    finally:
        reset_context(ctx_token)

    # Sanity: the row physically exists in the table.
    async with TestSession() as session:
        # Bypass the auto-tenant filter by setting context to org B.
        verify_token = set_context(RequestContext(org_id=org_b_id))
        try:
            from sqlalchemy import select

            count = (
                await session.execute(
                    select(Activity).where(Activity.entity_id == shared_entity)
                )
            ).scalars().all()
            assert len(count) == 1
        finally:
            reset_context(verify_token)

    # Now: log in as org A's admin and ask for the same entity_id's timeline.
    token = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={shared_entity}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_org_a_sees_own_activity_alongside_invisible_org_b_row(
    layered_client, seeded_admin
):
    """Sibling test: org A's own row is visible while org B's stays hidden."""
    from tests.conftest import TestSession

    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")

    org_b_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            Organization(
                id=org_b_id,
                name="OtherB",
                slug=f"otherb-{org_b_id.hex[:6]}",
            )
        )
        await session.commit()

    shared_entity = uuid.uuid4()

    # Org B logs an event.
    tb = set_context(RequestContext(org_id=org_b_id))
    try:
        await log(
            entity_type="contact",
            entity_id=shared_entity,
            type=ActivityType.note,
            payload={"text": "B note"},
        )
    finally:
        reset_context(tb)

    # Log in as A and add A's own note via HTTP.
    token = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = await layered_client.post(
        "/api/v1/activities",
        json={
            "entity_type": "contact",
            "entity_id": str(shared_entity),
            "type": "note",
            "payload": {"text": "A note"},
        },
        headers=headers,
    )
    assert resp.status_code == 201

    listing = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={shared_entity}",
        headers=headers,
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    texts = [i["payload"]["text"] for i in items]
    assert texts == ["A note"]
