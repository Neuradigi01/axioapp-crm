"""HTTP + service coverage for contacts assignee + last_activity_at.

Five tiny cases driven through the layered FastAPI app:

  1. `list?assigned_to_id={user}` returns only contacts assigned to
     that user.
  2. `list?sort=last_activity_at&order=desc` returns rows newest-first
     with NULL bumped to the bottom.
  3. `list?sort=evil` returns 422 (FastAPI Literal validation).
  4. Creating an activity on a contact bumps `last_activity_at` to
     the activity's `created_at`.
  5. Creating an *older* activity does not regress an already-newer
     `last_activity_at` (the `<` guard).

Run with: ``uv run pytest tests/test_contacts_assignee_and_last_activity.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import ActivityType
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


async def _make_contact(
    org_id: uuid.UUID,
    *,
    full_name: str,
    assigned_to_id: uuid.UUID | None = None,
    last_activity_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a contact directly via the ORM, bypassing the HTTP path.

    Used for setting `last_activity_at` to a known value — the HTTP
    create path doesn't accept it (server-managed field).
    """
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            contact = Contact(
                org_id=org_id,
                full_name=full_name,
                assigned_to_id=assigned_to_id,
                last_activity_at=last_activity_at,
            )
            session.add(contact)
            await session.commit()
            return contact.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_list_filters_by_assignee(layered_client, seeded_admin):
    """Only the contact assigned to `:user` comes back."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    mine = await _make_contact(org.id, full_name="Mine", assigned_to_id=user.legacy_uuid)
    await _make_contact(org.id, full_name="Theirs", assigned_to_id=None)

    listed = await layered_client.get(
        f"/api/v1/contacts?assigned_to_id={user.legacy_uuid}", headers=headers
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(mine)
    assert payload["items"][0]["full_name"] == "Mine"
    assert payload["items"][0]["assigned_to_id"] == str(user.legacy_uuid)


@pytest.mark.asyncio
async def test_list_sort_by_last_activity_desc_nulls_last(layered_client, seeded_admin):
    """`?sort=last_activity_at&order=desc` returns newest first; NULLs sink."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(UTC)
    older_id = await _make_contact(
        org.id, full_name="Older", last_activity_at=now - timedelta(hours=2)
    )
    newer_id = await _make_contact(
        org.id, full_name="Newer", last_activity_at=now - timedelta(minutes=10)
    )
    never_id = await _make_contact(org.id, full_name="Never", last_activity_at=None)

    listed = await layered_client.get(
        "/api/v1/contacts?sort=last_activity_at&order=desc",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [
        str(newer_id),
        str(older_id),
        str(never_id),
    ]


@pytest.mark.asyncio
async def test_list_rejects_unknown_sort_key(layered_client, seeded_admin):
    """FastAPI Literal validation rejects `sort=evil` with 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    bad = await layered_client.get("/api/v1/contacts?sort=evil", headers=headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_activity_insert_bumps_last_activity_at(layered_client, seeded_admin):
    """`POST /activities` on a contact bumps the contact's last_activity_at."""
    from sqlalchemy import select

    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "contacts.read",
        "contacts.write",
        "activities.read",
        "activities.write",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="Bump Me")

    resp = await layered_client.post(
        "/api/v1/activities",
        json={
            "entity_type": "contact",
            "entity_id": str(contact_id),
            "type": "note",
            "payload": {"text": "First contact made."},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            assert row.last_activity_at is not None
    finally:
        reset_context(ctx_token)


@pytest.mark.asyncio
async def test_older_activity_does_not_regress_last_activity_at(layered_client, seeded_admin):
    """The `<` guard prevents backfilling a past timestamp over a newer one."""
    from sqlalchemy import select

    from src.app.core.activities import log
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    # Login is unused here — we drive `log()` directly to control timestamps.
    await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    # Pre-seed a contact with a forward-dated last_activity_at.
    future = datetime.now(UTC) + timedelta(hours=1)
    contact_id = await _make_contact(org.id, full_name="Forward Dated", last_activity_at=future)

    # Drive `log()` under the tenant context — it will insert an
    # activity whose created_at is `now()` (i.e. older than `future`).
    ctx_token = set_context(RequestContext(org_id=org.id, user_id=user.legacy_uuid))
    try:
        await log(
            entity_type="contact",
            entity_id=contact_id,
            type=ActivityType.note,
            payload={"text": "older event"},
            org_id=org.id,
            user_id=user.legacy_uuid,
        )
    finally:
        reset_context(ctx_token)

    # Confirm the forward-dated timestamp survived (the bump no-ops
    # because activity.created_at < last_activity_at).
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            # Allow tiny serialization drift between SET and SELECT
            # (TZ-aware comparison only). Assert >= the original future
            # value — anything later would mean the bump regressed it.
            assert row.last_activity_at is not None
            assert row.last_activity_at >= future
    finally:
        reset_context(ctx_token)
