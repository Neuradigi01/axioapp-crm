"""HTTP-level coverage for the field-ops module.

Asserts:
  - POST /field-visits creates an appointment AND an fp_field_visits
    row in one transaction; the response carries the new visit.
  - GET /field-visits filters: assigned_to_id + completed.
  - POST /field-visits/{id}/complete:
      * sets completed_at + flips the appointment to status='completed'
      * is idempotent (re-calling doesn't double-write)
      * copies passed measurements back to a linked custom order
  - Permission gate: a user with only `field_visits.read` cannot create.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.appointments.models import (
    Appointment,
    AppointmentStatus,
)
from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.packs.furniture.modules.custom_orders.models import (
    CustomOrderMeasurement,
)
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
                full_name="Site Visit Tester",
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


def _appt_payload(contact_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    return {
        "contact_id": str(contact_id),
        "title": "Measurement at customer site",
        "purpose": "measurement",
        "scheduled_at": when,
        "duration_min": 60,
        "location": "Customer home",
        "assigned_to_id": str(user_id),
        "custom_data": {},
    }


@pytest.mark.asyncio
async def test_create_visit_creates_appointment_too(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "field_visits.read",
        "field_visits.write",
    )
    contact_id = await _seed_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/field-visits",
        json={
            "appointment": _appt_payload(contact_id, user.id),
            "purpose": "measurement",
            "notes": "bring laser measure",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["purpose"] == "measurement"
    assert body["completed_at"] is None

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            appt = (
                await session.execute(
                    select(Appointment).where(Appointment.id == uuid.UUID(body["appointment_id"]))
                )
            ).scalar_one()
            assert appt.title == "Measurement at customer site"
            assert appt.status == AppointmentStatus.scheduled
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_list_filters_by_assigned_and_completed(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "field_visits.read",
        "field_visits.write",
    )
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(2):
        r = await layered_client.post(
            "/api/v1/field-visits",
            json={
                "appointment": _appt_payload(contact_id, user.id),
                "purpose": "measurement",
            },
            headers=headers,
        )
        assert r.status_code == 201

    all_resp = await layered_client.get(
        f"/api/v1/field-visits?assigned_to_id={user.id}",
        headers=headers,
    )
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 2

    open_resp = await layered_client.get(
        f"/api/v1/field-visits?assigned_to_id={user.id}&completed=false",
        headers=headers,
    )
    assert open_resp.json()["total"] == 2

    closed_resp = await layered_client.get(
        f"/api/v1/field-visits?assigned_to_id={user.id}&completed=true",
        headers=headers,
    )
    assert closed_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_complete_flips_appointment_and_is_idempotent(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "field_visits.read",
        "field_visits.write",
    )
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/field-visits",
        json={
            "appointment": _appt_payload(contact_id, user.id),
            "purpose": "measurement",
        },
        headers=headers,
    )
    visit_id = create.json()["id"]
    appt_id = create.json()["appointment_id"]

    first = await layered_client.post(
        f"/api/v1/field-visits/{visit_id}/complete",
        json={"notes": "all good"},
        headers=headers,
    )
    assert first.status_code == 200
    completed_at_1 = first.json()["completed_at"]
    assert completed_at_1 is not None

    # Appointment should now be `completed`.
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            appt = (
                await session.execute(
                    select(Appointment).where(Appointment.id == uuid.UUID(appt_id))
                )
            ).scalar_one()
            assert appt.status == AppointmentStatus.completed
    finally:
        reset_context(ctx)

    # Re-call: idempotent — completed_at unchanged.
    second = await layered_client.post(
        f"/api/v1/field-visits/{visit_id}/complete",
        json={"notes": "ignore me"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["completed_at"] == completed_at_1


@pytest.mark.asyncio
async def test_complete_copies_measurements_to_linked_custom_order(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "field_visits.read",
        "field_visits.write",
        "custom_orders.read",
        "custom_orders.write",
    )
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    co = await layered_client.post(
        "/api/v1/custom-orders",
        json={"title": "Wardrobe build", "contact_id": str(contact_id)},
        headers=headers,
    )
    co_id = co.json()["id"]

    visit = await layered_client.post(
        "/api/v1/field-visits",
        json={
            "appointment": _appt_payload(contact_id, user.id),
            "purpose": "measurement",
            "custom_order_id": co_id,
        },
        headers=headers,
    )
    visit_id = visit.json()["id"]

    resp = await layered_client.post(
        f"/api/v1/field-visits/{visit_id}/complete",
        json={
            "notes": "measurement complete",
            "measurements": [
                {
                    "item_label": "Wardrobe body",
                    "length_cm": "220.00",
                    "width_cm": "60.00",
                    "height_cm": "240.00",
                },
                {"item_label": "Top shelf", "width_cm": "200.00"},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200

    # Both measurements should now be on the linked custom order.
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            rows = (
                (
                    await session.execute(
                        select(CustomOrderMeasurement).where(
                            CustomOrderMeasurement.order_id == uuid.UUID(co_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            labels = sorted(r.item_label for r in rows)
            assert labels == ["Top shelf", "Wardrobe body"]
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_write_requires_write_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "field_visits.read")
    contact_id = await _seed_contact(org.id)
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/field-visits",
        json={
            "appointment": _appt_payload(contact_id, user.id),
            "purpose": "measurement",
        },
        headers=headers,
    )
    assert resp.status_code == 403
