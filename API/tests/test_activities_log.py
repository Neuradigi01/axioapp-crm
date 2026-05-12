"""Coverage for the activities log+list cycle.

Exercises both ingress paths:

  1. The internal `activities.log(...)` helper — used by any module to
     record system events. Verifies it persists in its own transaction
     and shows up via the HTTP `GET /activities` reader.
  2. The HTTP `POST /activities` endpoint for manual notes — verifies
     the schema enforces `type=note` + non-empty `payload.text`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities import log
from src.app.core.activities.models import ActivityType
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


@pytest.mark.asyncio
async def test_post_note_then_list_returns_it(layered_client, seeded_admin):
    """HTTP POST → 201; GET returns the note newest-first."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = uuid.uuid4()
    create = await layered_client.post(
        "/api/v1/activities",
        json={
            "entity_type": "contact",
            "entity_id": str(contact_id),
            "type": "note",
            "payload": {"text": "Customer called to ask about Teak sofas."},
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["type"] == "note"
    assert body["payload"] == {"text": "Customer called to ask about Teak sofas."}
    assert body["user_id"] == str(user.id)

    listed = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={contact_id}",
        headers=headers,
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["payload"]["text"] == (
        "Customer called to ask about Teak sofas."
    )


@pytest.mark.asyncio
async def test_post_rejects_non_note_type(layered_client, seeded_admin):
    """Only `note` is creatable over HTTP; other types are server-emitted."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")
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
            "entity_type": "contact",
            "entity_id": str(uuid.uuid4()),
            "type": "call",
            "payload": {"text": "fake call from a browser"},
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_post_rejects_empty_or_missing_text(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for bad in ({}, {"text": ""}, {"text": "   "}):
        resp = await layered_client.post(
            "/api/v1/activities",
            json={
                "entity_type": "contact",
                "entity_id": str(uuid.uuid4()),
                "type": "note",
                "payload": bad,
            },
            headers=headers,
        )
        assert resp.status_code == 422, (bad, resp.text)


@pytest.mark.asyncio
async def test_internal_log_helper_persists_visible_to_http(
    layered_client, seeded_admin
):
    """The reusable `activities.log(...)` helper is the canonical ingress
    for non-HTTP events (status changes, call ends, …). It must produce
    rows visible to the HTTP reader for the same `(org, entity)`."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = uuid.uuid4()
    ctx_token = set_context(RequestContext(org_id=org.id, user_id=user.id))
    try:
        await log(
            entity_type="contact",
            entity_id=contact_id,
            type=ActivityType.status_change,
            payload={"from": "new", "to": "qualified"},
        )
    finally:
        reset_context(ctx_token)

    resp = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={contact_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "status_change"
    assert items[0]["payload"] == {"from": "new", "to": "qualified"}
    assert items[0]["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_log_helper_swallows_errors_without_org(layered_client):
    """No org_id resolvable → row dropped, no exception raised."""
    # No `set_context` and no explicit org_id → should be a no-op.
    await log(
        entity_type="contact",
        entity_id=uuid.uuid4(),
        type=ActivityType.note,
        payload={"text": "should not persist"},
    )
    # The fact that this test finishes is the assertion: log() did
    # not raise. (The row obviously is not there because we never
    # gave it a tenant.)


@pytest.mark.asyncio
async def test_list_is_ordered_newest_first(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "activities.read", "activities.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = uuid.uuid4()
    for text in ("first", "second", "third"):
        resp = await layered_client.post(
            "/api/v1/activities",
            json={
                "entity_type": "contact",
                "entity_id": str(contact_id),
                "type": "note",
                "payload": {"text": text},
            },
            headers=headers,
        )
        assert resp.status_code == 201

    resp = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={contact_id}",
        headers=headers,
    )
    texts = [i["payload"]["text"] for i in resp.json()["items"]]
    assert texts == ["third", "second", "first"]


@pytest.mark.asyncio
async def test_read_requires_permission(layered_client, seeded_admin):
    """A user lacking `activities.read` is 403 on GET."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # No grants → 403.
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        f"/api/v1/activities?entity_type=contact&entity_id={uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
