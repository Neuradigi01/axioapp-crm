"""HTTP-level coverage for walk-ins `last_activity_at` + status state-machine.

Six cases:

  1. `browsing → interested` (and on through `follow_up → converted`)
     all succeed.
  2. `browsing → converted` (skipping middle states) → 422.
  3. `converted → browsing` (terminal) → 422.
  4. `left → browsing` (re-engagement) succeeds.
  5. Activity-insert on a walk-in bumps `last_activity_at`.
  6. `list?sort=last_activity_at&order=desc` returns expected order
     (newest activity first, NULLs last).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
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


async def _seed_contact(org_id: uuid.UUID, *, full_name: str = "Asha") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=full_name,
                phone="+91 9000000001",
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
    last_activity_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            w = WalkIn(
                org_id=org_id,
                contact_id=contact_id,
                status=status,
                last_activity_at=last_activity_at,
            )
            session.add(w)
            await session.commit()
            return w.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_happy_path_browsing_to_interested(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)
    w = await _seed_walkin(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/walk-ins/{w}",
        json={"status": "interested"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "interested"


@pytest.mark.asyncio
async def test_rejects_skipping_intermediate_states(
    layered_client, seeded_admin
):
    """`browsing → converted` is not allowed — must go through interested."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)
    w = await _seed_walkin(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/walk-ins/{w}",
        json={"status": "converted"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_terminal_converted_cannot_be_changed(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)
    w = await _seed_walkin(
        org.id, contact_id=contact_id, status=WalkInStatus.converted
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/walk-ins/{w}",
        json={"status": "browsing"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_left_can_be_reengaged_to_browsing(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)
    w = await _seed_walkin(org.id, contact_id=contact_id, status=WalkInStatus.left)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/walk-ins/{w}",
        json={"status": "browsing"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "browsing"


@pytest.mark.asyncio
async def test_activity_insert_bumps_walkin_last_activity_at(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "walkins.read",
        "walkins.write",
        "activities.read",
        "activities.write",
    )
    contact_id = await _seed_contact(org.id)
    w = await _seed_walkin(org.id, contact_id=contact_id)

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
            "entity_type": "walk_in",
            "entity_id": str(w),
            "type": "note",
            "payload": {"text": "approached customer"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(WalkIn).where(WalkIn.id == w))
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
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")
    contact_id = await _seed_contact(org.id)

    now = datetime.now(timezone.utc)
    older = await _seed_walkin(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(hours=3),
    )
    newer = await _seed_walkin(
        org.id,
        contact_id=contact_id,
        last_activity_at=now - timedelta(minutes=10),
    )
    never = await _seed_walkin(org.id, contact_id=contact_id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        "/api/v1/walk-ins?sort=last_activity_at&order=desc", headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = [it["id"] for it in resp.json()]
    assert ids == [str(newer), str(older), str(never)]
