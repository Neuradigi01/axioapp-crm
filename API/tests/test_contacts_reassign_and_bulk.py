"""HTTP-level coverage for contacts reassign + bulk endpoints.

Six cases driven through the layered FastAPI app:

  1. `POST /contacts/{id}/reassign` writes the new owner.
  2. Same call creates an `activity` row of type `reassign`.
  3. Same call bumps `last_activity_at` on the contact.
  4. `POST /contacts/bulk-reassign` updates N rows + writes N activities.
  5. Cross-tenant target user → 422 (not a member of caller's org).
  6. Caller without `contacts.reassign` → 403.

The fixture `seeded_admin` grants every permission key the test
requests via `_grant(...)`; for the 403 case we deliberately omit
`contacts.reassign`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
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


async def _make_contact(
    org_id: uuid.UUID,
    *,
    full_name: str,
    assigned_to_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            contact = Contact(
                org_id=org_id,
                full_name=full_name,
                assigned_to_id=assigned_to_id,
            )
            session.add(contact)
            await session.commit()
            return contact.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_reassign_writes_owner_activity_and_bumps_last_activity(
    layered_client, seeded_admin
):
    """One endpoint hit covers test cases 1, 2, 3."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "contacts.read",
        "contacts.write",
        "contacts.reassign",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="Reassign Me")

    resp = await layered_client.post(
        f"/api/v1/contacts/{contact_id}/reassign",
        json={"assigned_to_id": str(user.legacy_uuid), "note": "transfer test"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assigned_to_id"] == str(user.legacy_uuid)

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(
                    select(Contact).where(Contact.id == contact_id)
                )
            ).scalar_one()
            assert row.assigned_to_id == user.legacy_uuid
            assert row.last_activity_at is not None  # bumped by hook

            activities = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "contact")
                    .where(Activity.entity_id == contact_id)
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(activities) == 1
            payload = activities[0].payload
            assert payload["from"] is None
            assert payload["to"] == str(user.legacy_uuid)
            assert payload["note"] == "transfer test"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_bulk_reassign_updates_all_and_writes_activities(
    layered_client, seeded_admin
):
    """`POST /contacts/bulk-reassign` rolls up to N reassigns + N activities."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "contacts.read",
        "contacts.write",
        "contacts.reassign",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    ids = [
        await _make_contact(org.id, full_name=f"Bulk {i}") for i in range(3)
    ]

    resp = await layered_client.post(
        "/api/v1/contacts/bulk-reassign",
        json={
            "ids": [str(i) for i in ids],
            "assigned_to_id": str(user.legacy_uuid),
            "note": None,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reassigned"] == 3

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            for cid in ids:
                row = (
                    await session.execute(
                        select(Contact).where(Contact.id == cid)
                    )
                ).scalar_one()
                assert row.assigned_to_id == user.legacy_uuid

            count = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_type == "contact")
                    .where(Activity.entity_id.in_(ids))
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(count) == 3
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_reassign_cross_tenant_target_rejected(
    layered_client, seeded_admin
):
    """Target UUID belongs to no membership in the caller's org → 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "contacts.read",
        "contacts.write",
        "contacts.reassign",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="Cross-Tenant")
    foreign_uuid = uuid.uuid4()

    resp = await layered_client.post(
        f"/api/v1/contacts/{contact_id}/reassign",
        json={"assigned_to_id": str(foreign_uuid), "note": None},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_reassign_without_permission_returns_403(
    layered_client, seeded_admin
):
    """Caller has contacts.read+write but NOT contacts.reassign → 403."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Deliberately omit `contacts.reassign`.
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="No-Perm")

    resp = await layered_client.post(
        f"/api/v1/contacts/{contact_id}/reassign",
        json={"assigned_to_id": str(user.legacy_uuid), "note": None},
        headers=headers,
    )
    assert resp.status_code == 403
