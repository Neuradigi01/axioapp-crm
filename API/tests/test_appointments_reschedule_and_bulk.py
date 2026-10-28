"""HTTP coverage for appointments reschedule + bulk endpoints (Step 3).

Four cases:

  1. `POST /appointments/{id}/reschedule` shifts `scheduled_at`,
     writes a `reschedule` audit activity, and bumps
     `last_activity_at`.
  2. Rescheduling a `completed` appointment → 422 (terminal state).
  3. `POST /appointments/bulk-cancel` over three scheduled rows
     transitions all to `cancelled` and writes three
     `status_change` activities.
  4. Bulk-cancel with one already-completed row in the batch
     returns `{cancelled: N, skipped: 1}` (partial success).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
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
                custom_data={},
            )
            session.add(a)
            await session.commit()
            return a.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_reschedule_shifts_slot_and_writes_audit(layered_client, seeded_admin):
    """Happy path. Server stamps `scheduled_at`, writes a `reschedule`
    activity carrying `from`/`to`/`reason`, and the activity-insert
    hook bumps `last_activity_at`."""
    from tests.conftest import TestSession

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

    new_slot = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    resp = await layered_client.post(
        f"/api/v1/appointments/{appt_id}/reschedule",
        json={"scheduled_at": new_slot, "reason": "customer requested earlier"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Appointment).where(Appointment.id == appt_id))
            ).scalar_one()
            assert row.last_activity_at is not None

            activities = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "appointment")
                        .where(Activity.entity_id == appt_id)
                        .where(Activity.type == ActivityType.reschedule)
                    )
                )
                .scalars()
                .all()
            )
            assert len(activities) == 1
            payload = activities[0].payload
            assert payload["reason"] == "customer requested earlier"
            assert "from" in payload and "to" in payload
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_reschedule_completed_appointment_rejected(layered_client, seeded_admin):
    """`completed` is terminal — the service rejects with 422."""
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

    new_slot = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    resp = await layered_client.post(
        f"/api/v1/appointments/{appt_id}/reschedule",
        json={"scheduled_at": new_slot, "reason": None},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_bulk_cancel_three_scheduled_writes_three_activities(layered_client, seeded_admin):
    """Three `scheduled` appointments → three `status_change` activities,
    every row transitioned to `cancelled`."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    # Disjoint slots so the seed doesn't trip the conflict check.
    now = datetime.now(UTC)
    ids = [
        await _seed_appointment(
            org.id,
            contact_id=contact_id,
            assigned_to_id=user.legacy_uuid,
            scheduled_at=now + timedelta(days=1, hours=i * 2),
        )
        for i in range(3)
    ]

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/appointments/bulk-cancel",
        json={"ids": [str(i) for i in ids], "reason": "store closing"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cancelled"] == 3
    assert body["skipped"] == 0

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            for aid in ids:
                row = (
                    await session.execute(select(Appointment).where(Appointment.id == aid))
                ).scalar_one()
                assert row.status == AppointmentStatus.cancelled

            activities = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "appointment")
                        .where(Activity.entity_id.in_(ids))
                        .where(Activity.type == ActivityType.status_change)
                    )
                )
                .scalars()
                .all()
            )
            assert len(activities) == 3
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_cancel_partial_success_with_completed_row(layered_client, seeded_admin):
    """Mix of two `scheduled` + one `completed` → cancelled=2, skipped=1."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    now = datetime.now(UTC)
    sched_a = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=1),
    )
    sched_b = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=3),
    )
    done = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=user.legacy_uuid,
        scheduled_at=now + timedelta(days=1, hours=5),
        status=AppointmentStatus.completed,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/appointments/bulk-cancel",
        json={
            "ids": [str(sched_a), str(sched_b), str(done)],
            "reason": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cancelled"] == 2
    assert body["skipped"] == 1
