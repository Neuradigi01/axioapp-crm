"""HTTP coverage for the notifications emitted by the appointments module
(Step 5 of update-appointments-page).

Four notification types fire from appointments/service.py:
  - `appointment.assigned`    (on create + on reassign single + bulk)
  - `appointment.rescheduled` (on reschedule)
  - `appointment.cancelled`   (on PATCH status -> cancelled)
  - `appointment.completed`   (on PATCH status -> completed)

Self-spam suppression: when the recipient == actor, no row is written.
Reschedule and completed fire unconditionally (paper trail).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.contacts.models import Contact
from src.app.core.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.users.models import OrganizationMember, UserInfo
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password as _hp
from src.models.user import UserLogin

# --- helpers ---------------------------------------------------------------


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


async def _seed_contact(org_id: uuid.UUID, *, name: str = "Asha") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=name,
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_second_user(
    org_id: uuid.UUID, *, role_id: uuid.UUID, first_name: str = "Priya"
) -> uuid.UUID:
    """Insert a second user in the same org and return their
    `legacy_uuid` (the UUID every cross-table FK references)."""
    from tests.conftest import TestSession

    user_uuid = uuid.uuid4()
    login_handle = f"second-{uuid.uuid4().hex[:8]}"

    async with TestSession() as session:
        login = UserLogin(
            user_id=login_handle,
            password=_hp("Pass@123"),
            is_active=True,
        )
        session.add(login)
        await session.flush()

        await session.execute(
            sql_text("UPDATE tbl_user_login SET legacy_uuid = :u WHERE id = :i"),
            {"u": str(user_uuid), "i": login.id},
        )
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": str(user_uuid)},
        )
        session.add(
            UserInfo(
                member_id=login.id,
                first_name=first_name,
                last_name="Test",
                email=f"{first_name.lower()}-{uuid.uuid4().hex[:6]}@demo.local",
                mobile_no="0000000099",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_member_id=login.id,
                role_id=role_id,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()
    return user_uuid


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
                scheduled_at=scheduled_at or datetime.now(UTC) + timedelta(days=1, hours=2),
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


async def _notifications_for(user_id: uuid.UUID, *, type_: str | None = None) -> list[Notification]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if type_ is not None:
            stmt = stmt.where(Notification.type == type_)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


def _ts(hour: int, days_offset: int = 1) -> str:
    base = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=days_offset
    )
    return base.isoformat()


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_assigned_to_other_user_notifies(layered_client, seeded_admin):
    """Owner books an appointment for Priya -> one notification row."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]  # current_user_id = actor.legacy_uuid
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="Asha Reddy")
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="Priya"
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Sofa selection",
            "scheduled_at": _ts(10),
            "duration_min": 60,
            "location": "Banjara Hills",
            "assigned_to_id": str(priya_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    appt_id = resp.json()["id"]

    notifs = await _notifications_for(priya_uuid, type_="appointment.assigned")
    assert len(notifs) == 1
    n = notifs[0]
    assert n.title == "New appointment: Sofa selection"
    assert "Asha Reddy" in (n.body or "")
    assert n.payload["appointment_id"] == appt_id
    assert n.payload["contact_name"] == "Asha Reddy"
    assert n.payload["actor_user_id"] == str(actor.legacy_uuid)


@pytest.mark.asyncio
async def test_create_assigned_to_self_does_not_notify(layered_client, seeded_admin):
    """Owner books for themselves -> no notification."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Self booking",
            "scheduled_at": _ts(11),
            "duration_min": 30,
            "assigned_to_id": str(actor.legacy_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text

    notifs = await _notifications_for(actor.legacy_uuid)
    assert notifs == []


@pytest.mark.asyncio
async def test_reassign_notifies_new_owner(layered_client, seeded_admin):
    """Single-row reassign -> notification fires for the new owner."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "appointments.read",
        "appointments.write",
        "appointments.reassign",
    )
    contact_id = await _seed_contact(org.id, name="Ravi K")
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="Priya"
    )
    rahul_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="Rahul"
    )
    appt_id = await _seed_appointment(org.id, contact_id=contact_id, assigned_to_id=priya_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        f"/api/v1/appointments/{appt_id}/reassign",
        json={"assigned_to_id": str(rahul_uuid), "note": "shift swap"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rahul_notifs = await _notifications_for(rahul_uuid, type_="appointment.assigned")
    priya_notifs = await _notifications_for(priya_uuid)
    assert len(rahul_notifs) == 1
    assert rahul_notifs[0].payload["appointment_id"] == str(appt_id)
    # Losing assignment doesn't generate a notification for Priya.
    assert priya_notifs == []


@pytest.mark.asyncio
async def test_bulk_reassign_emits_one_per_moved_row(layered_client, seeded_admin):
    """Bulk reassign 3 rows -> 3 notifications for the new owner."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "appointments.read",
        "appointments.write",
        "appointments.reassign",
    )
    contact_id = await _seed_contact(org.id, name="Bulk Reassign")
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaB"
    )
    rahul_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="RahulB"
    )

    ids: list[str] = []
    for i in range(3):
        aid = await _seed_appointment(
            org.id,
            contact_id=contact_id,
            assigned_to_id=priya_uuid,
            scheduled_at=datetime.now(UTC) + timedelta(days=2, hours=i * 3),
        )
        ids.append(str(aid))

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments/bulk-reassign",
        json={"ids": ids, "assigned_to_id": str(rahul_uuid), "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    rahul_notifs = await _notifications_for(rahul_uuid, type_="appointment.assigned")
    assert len(rahul_notifs) == 3
    moved_ids = {n.payload["appointment_id"] for n in rahul_notifs}
    assert moved_ids == set(ids)


@pytest.mark.asyncio
async def test_reschedule_notifies_owner(layered_client, seeded_admin):
    """Owner reschedules Priya's appointment -> Priya gets the notification."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaR"
    )
    appt_id = await _seed_appointment(org.id, contact_id=contact_id, assigned_to_id=priya_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    new_at = (datetime.now(UTC) + timedelta(days=2, hours=4)).isoformat()
    resp = await layered_client.post(
        f"/api/v1/appointments/{appt_id}/reschedule",
        json={"scheduled_at": new_at, "reason": "vendor pushed back"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    notifs = await _notifications_for(priya_uuid, type_="appointment.rescheduled")
    assert len(notifs) == 1
    assert notifs[0].payload["appointment_id"] == str(appt_id)


@pytest.mark.asyncio
async def test_cancel_for_other_user_notifies(layered_client, seeded_admin):
    """Owner cancels Priya's appointment -> Priya gets a cancellation
    notification. Status-change is a PATCH on the appointment."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="Mr Cancel")
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaC"
    )
    appt_id = await _seed_appointment(org.id, contact_id=contact_id, assigned_to_id=priya_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    notifs = await _notifications_for(priya_uuid, type_="appointment.cancelled")
    assert len(notifs) == 1
    assert notifs[0].payload["appointment_id"] == str(appt_id)
    assert "Mr Cancel" in (notifs[0].body or "")


@pytest.mark.asyncio
async def test_cancel_by_self_does_not_notify(layered_client, seeded_admin):
    """Owner cancels their own appointment -> no notification."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    appt_id = await _seed_appointment(
        org.id, contact_id=contact_id, assigned_to_id=actor.legacy_uuid
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    notifs = await _notifications_for(actor.legacy_uuid)
    assert notifs == []


@pytest.mark.asyncio
async def test_preference_off_suppresses_notification(layered_client, seeded_admin):
    """Priya disables in_app for `appointment.assigned` -> next booking
    does NOT write a notification row."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="Quiet Customer")
    priya_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaQ"
    )

    # Persist Priya's preference: in_app OFF for appointment.assigned.
    async with TestSession() as session:
        session.add(
            NotificationPreference(
                org_id=org.id,
                user_id=priya_uuid,
                type="appointment.assigned",
                channel=NotificationChannel.in_app,
                enabled=False,
            )
        )
        await session.commit()

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Quiet hours",
            "scheduled_at": _ts(13),
            "duration_min": 45,
            "assigned_to_id": str(priya_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text

    notifs = await _notifications_for(priya_uuid)
    assert notifs == []
