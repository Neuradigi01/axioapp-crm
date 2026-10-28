"""Coverage for /api/v1/walk-ins/quick-register.

Asserts:
  - new phone → creates contact AND walk-in
  - existing phone → reuses contact (no dup), creates walk-in
  - response carries both walk-in + contact + was_created flag
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
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


@pytest.mark.asyncio
async def test_new_phone_creates_contact_and_walk_in(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/walk-ins/quick-register",
        json={
            "phone": "+91 9999000001",
            "full_name": "Walk-in Customer 1",
            "source": "walk_in",
            "requirement": "3-seater sofa, Teak preferred",
            "budget": "60000.00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["contact_was_created"] is True
    assert body["walk_in"]["status"] == "browsing"
    assert body["walk_in"]["requirement"] == "3-seater sofa, Teak preferred"
    assert body["walk_in"]["budget"] == "60000.00"
    assert body["walk_in"]["contact_id"] == body["contact"]["id"]
    assert body["contact"]["full_name"] == "Walk-in Customer 1"
    assert body["contact"]["phone"] == "+91 9999000001"
    assert body["contact"]["source"] == "walk_in"


@pytest.mark.asyncio
async def test_existing_phone_reuses_contact(layered_client, seeded_admin):
    """Same phone in same org → reuses the contact, no duplicate row."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "walkins.write")

    # Pre-seed a contact under the org.
    phone = "+91 9999000002"
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            existing = Contact(
                org_id=org.id,
                full_name="Existing Customer",
                phone=phone,
                source="referral",
                custom_data={},
                tags=["vip"],
            )
            session.add(existing)
            await session.commit()
            existing_id = existing.id
    finally:
        reset_context(ctx)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/walk-ins/quick-register",
        json={
            "phone": phone,
            "full_name": "Different Name In Form",  # ignored — contact reused
            "requirement": "looking for dining set",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["contact_was_created"] is False
    assert body["contact"]["id"] == str(existing_id)
    assert body["contact"]["full_name"] == "Existing Customer"  # original name
    assert body["contact"]["tags"] == ["vip"]
    assert body["walk_in"]["contact_id"] == str(existing_id)

    # Sanity: only one contact with this phone in the org.
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            rows = (
                (await session.execute(select(Contact).where(Contact.phone == phone)))
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_quick_register_requires_perm(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/walk-ins/quick-register",
        json={"phone": "+91 9999000003", "full_name": "Should Fail"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
