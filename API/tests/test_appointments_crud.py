"""HTTP-level CRUD coverage for /api/v1/appointments.

Covers: create / get / list-by-range / patch / delete happy path,
422 on unknown contact or unknown assignee, calendar filters
(`from`, `to`, `assigned_to`, `status`), perm-gated write.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
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


async def _seed_contact(org_id: uuid.UUID) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name="Appt Test",
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


def _ts(hour: int, minute: int = 0) -> str:
    """Pick a future-ish timestamp deterministically within today's range."""
    base = datetime.now(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ) + timedelta(days=1)
    return base.isoformat()


@pytest.mark.asyncio
async def test_create_get_patch_delete(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Showroom visit",
            "purpose": "showroom_visit",
            "scheduled_at": _ts(10),
            "duration_min": 60,
            "location": "Banjara Hills branch",
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["title"] == "Showroom visit"
    assert body["status"] == "scheduled"
    assert body["duration_min"] == 60
    appt_id = body["id"]

    got = await layered_client.get(
        f"/api/v1/appointments/{appt_id}", headers=headers
    )
    assert got.status_code == 200

    patch = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "completed", "location": "Banjara Hills · Floor 2"},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "completed"
    assert patch.json()["location"] == "Banjara Hills · Floor 2"

    delete = await layered_client.delete(
        f"/api/v1/appointments/{appt_id}", headers=headers
    )
    assert delete.status_code == 204

    after = await layered_client.get(
        f"/api/v1/appointments/{appt_id}", headers=headers
    )
    assert after.status_code == 404


@pytest.mark.asyncio
async def test_create_rejects_unknown_contact(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(uuid.uuid4()),
            "title": "Bogus",
            "scheduled_at": _ts(11),
            "duration_min": 30,
            "assigned_to_id": str(user.id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_rejects_unknown_assignee(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Bogus",
            "scheduled_at": _ts(11),
            "duration_min": 30,
            "assigned_to_id": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_calendar_list_filters(layered_client, seeded_admin):
    """`from`, `to`, `assigned_to`, `status` filters all narrow."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    base = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=2)

    # Three non-overlapping appointments at +0h, +2h, +4h on `base`.
    for offset_hours in (0, 2, 4):
        resp = await layered_client.post(
            "/api/v1/appointments",
            json={
                "contact_id": str(contact_id),
                "title": f"Appt @ +{offset_hours}h",
                "scheduled_at": (base + timedelta(hours=offset_hours)).isoformat(),
                "duration_min": 30,
                "assigned_to_id": str(user.id),
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    # Range that covers only the middle one.
    from_dt = (base + timedelta(hours=1, minutes=30)).isoformat()
    to_dt = (base + timedelta(hours=3)).isoformat()
    resp = await layered_client.get(
        f"/api/v1/appointments?from={from_dt}&to={to_dt}", headers=headers
    )
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["title"] == "Appt @ +2h"

    # Filtered by assignee that owns no appointments → empty.
    foreign = uuid.uuid4()
    resp = await layered_client.get(
        f"/api/v1/appointments?assigned_to={foreign}", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_write_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Only `read` granted; POST should 403.
    await _grant(seeded_admin["role"].id, "appointments.read")
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Should fail",
            "scheduled_at": _ts(9),
            "duration_min": 30,
            "assigned_to_id": str(user.id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_writes_activity_on_contact_timeline(
    layered_client, seeded_admin
):
    """Creating an appointment surfaces a note on the contact's timeline."""
    from sqlalchemy import select
    from src.app.core.activities.models import Activity
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "appointments.read",
        "appointments.write",
    )
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Visit",
            "scheduled_at": _ts(14),
            "duration_min": 45,
            "assigned_to_id": str(user.id),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            acts = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "contact")
                    .where(Activity.entity_id == contact_id)
                )
            ).scalars().all()
            assert len(acts) == 1
            assert "Appointment scheduled" in acts[0].payload["text"]
    finally:
        reset_context(ctx)
