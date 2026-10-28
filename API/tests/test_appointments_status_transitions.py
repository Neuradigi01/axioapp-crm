"""HTTP coverage for appointments `last_activity_at` + status state-machine.

Six cases (mirrors `test_walkins_last_activity_and_status.py`):

  1. `scheduled → completed` succeeds.
  2. `scheduled → scheduled` (identity no-op) rejected with 422.
  3. `completed → scheduled` (terminal) rejected with 422.
  4. `cancelled → scheduled` (rebook) succeeds.
  5. Activity-insert on an appointment bumps `last_activity_at`.
  6. `list?sort=last_activity_at&order=desc` returns expected order
     (newest activity first, NULLs last).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.appointments.models import Appointment, AppointmentStatus
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


async def _seed_appointment(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    assigned_to_id: uuid.UUID,
    status: AppointmentStatus = AppointmentStatus.scheduled,
    scheduled_at: datetime | None = None,
    last_activity_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            a = Appointment(
                org_id=org_id,
                contact_id=contact_id,
                title="Showroom visit",
                scheduled_at=scheduled_at or datetime.now(UTC) + timedelta(days=1),
                duration_min=60,
                assigned_to_id=assigned_to_id,
                status=status,
                last_activity_at=last_activity_at,
                custom_data={},
            )
            session.add(a)
            await session.commit()
            return a.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_scheduled_to_completed_succeeds(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    appt_id = await _seed_appointment(
        org.id, contact_id=contact_id, assigned_to_id=user.legacy_uuid
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "completed"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_identity_transition_rejected(layered_client, seeded_admin):
    """`scheduled → scheduled` should be rejected — a no-op should not
    ride along on a PATCH that's only changing other fields."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    appt_id = await _seed_appointment(
        org.id, contact_id=contact_id, assigned_to_id=user.legacy_uuid
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "scheduled"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_terminal_completed_cannot_be_changed(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    appt_id = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        status=AppointmentStatus.completed,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "scheduled"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_cancelled_can_be_rebooked_to_scheduled(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    # Future slot so the conflict re-check on `scheduled_at` doesn't
    # complain about a past appointment.
    future = datetime.now(UTC) + timedelta(days=2)
    appt_id = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        status=AppointmentStatus.cancelled,
        scheduled_at=future,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "scheduled"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scheduled"


@pytest.mark.asyncio
async def test_activity_insert_bumps_appointment_last_activity_at(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "appointments.read",
        "appointments.write",
        "activities.read",
        "activities.write",
    )
    contact_id = await _seed_contact(org.id)
    appt_id = await _seed_appointment(
        org.id, contact_id=contact_id, assigned_to_id=user.legacy_uuid
    )

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
            "entity_type": "appointment",
            "entity_id": str(appt_id),
            "type": "note",
            "payload": {"text": "confirmed via call"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Appointment).where(Appointment.id == appt_id))
            ).scalar_one()
            assert row.last_activity_at is not None
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_list_sort_by_last_activity_desc_nulls_last(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    now = datetime.now(UTC)
    # Three appointments with disjoint scheduled slots so the
    # default conflict check is happy on seed.
    older = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=1),
        last_activity_at=now - timedelta(hours=3),
    )
    newer = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=3),
        last_activity_at=now - timedelta(minutes=10),
    )
    never = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=5),
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        "/api/v1/appointments?sort=last_activity_at&order=desc",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = [it["id"] for it in resp.json()]
    assert ids == [str(newer), str(older), str(never)]
