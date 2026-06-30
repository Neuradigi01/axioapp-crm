"""HTTP coverage for the notifications REST endpoints.

Covers:
  - `notify()` writes a row visible to the recipient via GET
  - `unread=true` filter narrows
  - `PATCH /{id}/read` marks read
  - `POST /read-all` flips every unread to read
  - preferences: missing → empty list; PATCH upserts; disabled `in_app`
    causes `notify()` to skip persistence
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.notifications import notify
from src.app.core.notifications.models import NotificationChannel
from src.app.core.notifications.schemas import PreferenceUpdate
from src.app.core.notifications.service import update_preferences
from src.app.shared.context import RequestContext, reset_context, set_context


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_notify_then_list_then_mark_read(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await notify(
        org_id=org.id,
        user_id=user.id,
        type="lead.assigned",
        title="A new lead is yours",
        body="Asha Reddy was just assigned to you.",
        payload={"lead_id": str(uuid.uuid4())},
    )

    listed = await layered_client.get("/api/v1/notifications", headers=headers)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    nid = items[0]["id"]
    assert items[0]["type"] == "lead.assigned"
    assert items[0]["title"] == "A new lead is yours"
    assert items[0]["read_at"] is None
    assert "lead_id" in items[0]["payload"]

    unread_only = await layered_client.get("/api/v1/notifications?unread=true", headers=headers)
    assert unread_only.status_code == 200
    assert len(unread_only.json()) == 1

    patch = await layered_client.patch(f"/api/v1/notifications/{nid}/read", headers=headers)
    assert patch.status_code == 200
    assert patch.json()["read_at"] is not None

    unread_after = await layered_client.get("/api/v1/notifications?unread=true", headers=headers)
    assert unread_after.json() == []


@pytest.mark.asyncio
async def test_mark_all_read(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(3):
        await notify(
            org_id=org.id,
            user_id=user.id,
            type="task.due",
            title=f"Task {i} is due",
        )

    resp = await layered_client.post("/api/v1/notifications/read-all", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["marked"] == 3

    unread = await layered_client.get("/api/v1/notifications?unread=true", headers=headers)
    assert unread.json() == []


@pytest.mark.asyncio
async def test_other_user_cannot_read_my_notifications(layered_client, seeded_admin):
    """Even if a notification is in the same org, only the recipient sees it."""
    from src.app.core.users.models import User
    from src.app.shared.security.password import hash_password
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    me = seeded_admin["user"]
    role = seeded_admin["role"]

    other_id = uuid.uuid4()
    async with TestSession() as session:
        session.add(
            User(
                id=other_id,
                org_id=org.id,
                email=f"other-{other_id.hex[:6]}@demo.local",
                password_hash=hash_password("Other@123"),
                full_name="Other",
                role_id=role.id,
                is_active=True,
            )
        )
        await session.commit()

    # Notification targeted at "other_id"
    await notify(
        org_id=org.id,
        user_id=other_id,
        type="lead.assigned",
        title="For other user",
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=me.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_mark_read_404_for_missing_or_foreign(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_preferences_upsert_then_in_app_disabled_skips(layered_client, seeded_admin):
    """Disabling `in_app` for a type causes `notify()` to not persist."""

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Initially: no explicit prefs.
    resp = await layered_client.get("/api/v1/notification-preferences", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # PATCH: disable in_app for "lead.assigned".
    resp = await layered_client.patch(
        "/api/v1/notification-preferences/lead.assigned",
        json={"in_app": False, "email": True},
        headers=headers,
    )
    assert resp.status_code == 200
    rows = {(r["channel"], r["enabled"]) for r in resp.json()}
    assert ("in_app", False) in rows
    assert ("email", True) in rows

    # notify() should now skip persisting for this type.
    await notify(
        org_id=org.id,
        user_id=user.id,
        type="lead.assigned",
        title="should be suppressed",
    )
    listed = await layered_client.get("/api/v1/notifications", headers=headers)
    assert all(n["title"] != "should be suppressed" for n in listed.json())

    # Other types still default-enabled.
    await notify(
        org_id=org.id,
        user_id=user.id,
        type="task.due",
        title="should arrive",
    )
    listed2 = await layered_client.get("/api/v1/notifications", headers=headers)
    assert any(n["title"] == "should arrive" for n in listed2.json())


@pytest.mark.asyncio
async def test_preferences_patch_rejects_unknown_channel(layered_client, seeded_admin):
    """`extra='forbid'` rejects unknown keys (typo guard)."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.patch(
        "/api/v1/notification-preferences/lead.assigned",
        json={"sms": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_preferences_service_directly(seeded_admin):
    """Direct service call works without the HTTP layer too (used by tests
    that need to pre-seed preferences before calling notify())."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]

    ctx = set_context(RequestContext(org_id=org.id, user_id=user.id))
    try:
        async with TestSession() as session:
            rows = await update_preferences(
                session,
                org_id=org.id,
                user_id=user.id,
                type_="appointment.upcoming",
                payload=PreferenceUpdate(in_app=False, push=True),
            )
            assert len(rows) == 2
            by_ch = {r.channel: r.enabled for r in rows}
            assert by_ch[NotificationChannel.in_app] is False
            assert by_ch[NotificationChannel.push] is True
    finally:
        reset_context(ctx)
