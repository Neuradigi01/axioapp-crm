"""Coverage for appointment conflict detection.

Reproduces the master-prompt verification:
  - A: 10:00–11:00 for user X → 201
  - B: 10:30–11:30 for user X → 409
  - C: 10:30–11:30 for user Y → 201

Plus a handful of edge cases:
  - back-to-back appointments (start = previous.end) → not a conflict
  - PATCH that would create a conflict → 409
  - cancelled / no-show appointments don't block their slot
  - PATCH of the appointment's own time is allowed (exclude self)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password


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
            c = Contact(org_id=org_id, full_name="Conf Test", custom_data={}, tags=[])
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_extra_user(
    org_id: uuid.UUID, role_id: uuid.UUID
) -> uuid.UUID:
    from tests.conftest import TestSession

    user_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            User(
                id=user_id,
                org_id=org_id,
                email=f"extra-{user_id.hex[:6]}@demo.local",
                password_hash=hash_password("Extra@123"),
                full_name="Extra User",
                role_id=role_id,
                is_active=True,
            )
        )
        await session.commit()
    return user_id


def _at(hour: int, minute: int = 0) -> str:
    """Deterministic timestamp slot tomorrow."""
    base = datetime.now(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ) + timedelta(days=3)
    return base.isoformat()


@pytest.mark.asyncio
async def test_master_prompt_conflict_scenario(layered_client, seeded_admin):
    """A 10–11 user X · B 10:30–11:30 user X (409) · C 10:30–11:30 user Y (201)."""
    org = seeded_admin["org"]
    user_x = seeded_admin["user"]
    role = seeded_admin["role"]
    await _grant(role.id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    user_y = await _seed_extra_user(org.id, role.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user_x.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    a = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "A",
            "scheduled_at": _at(10),
            "duration_min": 60,
            "assigned_to_id": str(user_x.id),
        },
        headers=headers,
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["id"]

    b = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "B",
            "scheduled_at": _at(10, 30),
            "duration_min": 60,
            "assigned_to_id": str(user_x.id),
        },
        headers=headers,
    )
    assert b.status_code == 409, b.text
    body = b.json()
    assert "conflicts" in body
    assert a_id in body["conflicts"]

    c = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "C",
            "scheduled_at": _at(10, 30),
            "duration_min": 60,
            "assigned_to_id": str(user_y),
        },
        headers=headers,
    )
    assert c.status_code == 201, c.text


@pytest.mark.asyncio
async def test_back_to_back_is_not_a_conflict(layered_client, seeded_admin):
    """A ends at exactly when B begins → no overlap, no 409."""
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

    a = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "A",
            "scheduled_at": _at(13),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert a.status_code == 201, a.text

    b = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "B",
            "scheduled_at": _at(14),  # starts exactly when A ends
            "duration_min": 30,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert b.status_code == 201, b.text


@pytest.mark.asyncio
async def test_patch_into_conflict_is_rejected(layered_client, seeded_admin):
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

    a = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "A",
            "scheduled_at": _at(9),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["id"]

    b = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "B",
            "scheduled_at": _at(11),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert b.status_code == 201, b.text
    b_id = b.json()["id"]

    # Try to move B back into A's slot → 409.
    patch = await layered_client.patch(
        f"/api/v1/appointments/{b_id}",
        json={"scheduled_at": _at(9, 30)},
        headers=headers,
    )
    assert patch.status_code == 409, patch.text
    assert a_id in patch.json()["conflicts"]


@pytest.mark.asyncio
async def test_patch_own_time_is_allowed(layered_client, seeded_admin):
    """Editing other fields on an appointment doesn't conflict with itself."""
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

    a = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "A",
            "scheduled_at": _at(8),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["id"]

    # PATCH to extend duration while keeping start fixed — the row's
    # conflict check should exclude itself.
    patch = await layered_client.patch(
        f"/api/v1/appointments/{a_id}",
        json={"duration_min": 90},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["duration_min"] == 90


@pytest.mark.asyncio
async def test_cancelled_appointment_does_not_block(
    layered_client, seeded_admin
):
    """Once A is cancelled, B can take its slot."""
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

    a = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "A",
            "scheduled_at": _at(15),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert a.status_code == 201
    a_id = a.json()["id"]

    # Without cancelling, conflict.
    b_first = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "B (clash)",
            "scheduled_at": _at(15),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert b_first.status_code == 409

    # Cancel A.
    await layered_client.patch(
        f"/api/v1/appointments/{a_id}",
        json={"status": "cancelled"},
        headers=headers,
    )

    # Now B fits.
    b = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "B (ok)",
            "scheduled_at": _at(15),
            "duration_min": 60,
            "assigned_to_id": str(user.id),
        },
        headers=headers,
    )
    assert b.status_code == 201, b.text
