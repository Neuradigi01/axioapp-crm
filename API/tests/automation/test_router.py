"""Router-layer tests for ``core.automation.router``.

Exercises the nine endpoints via the layered ASGI app
(``layered_client`` fixture) — happy-path CRUD, permission gating,
RLS isolation, template/channel validation, condition validation,
event-type discovery, and run-history pagination.

Auth uses ``seeded_admin`` from conftest. The three
``automations.*`` perm keys are granted per-test via ``_grant_keys``
so each scenario is hermetic.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission

pytestmark = pytest.mark.asyncio


_AUTOMATION_KEYS = (
    "automations.read",
    "automations.write",
    "automations.runs.read",
)


async def _grant_keys(role_id: uuid.UUID, *keys: str) -> None:
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


async def _login(layered_client, *, org_slug: str, email: str, password: str) -> str:
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_email_template(layered_client, headers) -> str:
    """Create an email template via the central library + return its
    UUID. Triggers reference these by id."""
    resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": f"AutoTpl-{uuid.uuid4().hex[:6]}",
            "channel": "email",
            "category": "transactional",
            "body_text": "Hi {{ contact.first_name }}",
            "subject": "Hello",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- list + create ---------------------------------------------------


async def test_list_empty_returns_zero(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "automations.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/automations/triggers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_create_then_read(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.read",
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)

    create_resp = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "Welcome email",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": template_id,
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    tid = create_resp.json()["id"]
    assert create_resp.json()["enabled"] is True

    get_resp = await layered_client.get(f"/api/v1/automations/triggers/{tid}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["event_type"] == "user.signed_up"


async def test_create_requires_write_perm(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "automations.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "X",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_create_channel_template_mismatch_returns_422(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    email_template_id = await _seed_email_template(layered_client, headers)

    resp = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "MismatchedWA",
            "event_type": "user.signed_up",
            "channel": "whatsapp",  # template is email — mismatch!
            "template_id": email_template_id,
        },
        headers=headers,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "automation.template_channel_mismatch"


async def test_create_invalid_condition_returns_422(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)

    resp = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "BadCondition",
            "event_type": "lead.created",
            "channel": "email",
            "template_id": template_id,
            "conditions": {"op": "weird", "field": "x", "value": 1},
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "automation.invalid_condition"


async def test_create_duplicate_name_returns_409(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)
    body = {
        "name": "Dup",
        "event_type": "user.signed_up",
        "channel": "email",
        "template_id": template_id,
    }
    r1 = await layered_client.post("/api/v1/automations/triggers", json=body, headers=headers)
    assert r1.status_code == 201
    body["name"] = "dup"  # case collision
    r2 = await layered_client.post("/api/v1/automations/triggers", json=body, headers=headers)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "automation.duplicate_trigger_name"


# --- patch + enable/disable -----------------------------------------


async def test_patch_updates_fields(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)
    create = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "Trigger A",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": template_id,
        },
        headers=headers,
    )
    tid = create.json()["id"]
    patch = await layered_client.patch(
        f"/api/v1/automations/triggers/{tid}",
        json={"delay_seconds": 600, "name": "Trigger A v2"},
        headers=headers,
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["delay_seconds"] == 600
    assert body["name"] == "Trigger A v2"


async def test_enable_disable_idempotent(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)
    create = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "Toggleable",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": template_id,
            "enabled": True,
        },
        headers=headers,
    )
    tid = create.json()["id"]
    r1 = await layered_client.post(f"/api/v1/automations/triggers/{tid}/disable", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["enabled"] is False
    r2 = await layered_client.post(f"/api/v1/automations/triggers/{tid}/disable", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False
    r3 = await layered_client.post(f"/api/v1/automations/triggers/{tid}/enable", headers=headers)
    assert r3.status_code == 200
    assert r3.json()["enabled"] is True


# --- delete + 404 ----------------------------------------------------


async def test_delete_returns_204_then_404(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.write",
        "automations.read",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)
    create = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "Doomed",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": template_id,
        },
        headers=headers,
    )
    tid = create.json()["id"]
    delete = await layered_client.delete(f"/api/v1/automations/triggers/{tid}", headers=headers)
    assert delete.status_code == 204
    second = await layered_client.get(f"/api/v1/automations/triggers/{tid}", headers=headers)
    assert second.status_code == 404


# --- runs ------------------------------------------------------------


async def test_runs_endpoint_requires_runs_read_perm(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "automations.read",
        "automations.write",
        "templates.read",
        "templates.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    template_id = await _seed_email_template(layered_client, headers)
    create = await layered_client.post(
        "/api/v1/automations/triggers",
        json={
            "name": "RunsTest",
            "event_type": "user.signed_up",
            "channel": "email",
            "template_id": template_id,
        },
        headers=headers,
    )
    tid = create.json()["id"]
    resp = await layered_client.get(f"/api/v1/automations/triggers/{tid}/runs", headers=headers)
    # Without automations.runs.read, expect 403.
    assert resp.status_code == 403


# --- event discovery -----------------------------------------------


async def test_event_types_discovery_returns_catalog(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "automations.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/automations/event-types",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    entries = resp.json()
    event_types = {e["event_type"] for e in entries}
    # The two manager-spec'd defaults must always be present.
    assert "user.signed_up" in event_types
    assert "lead.created" in event_types
    # Each entry has a label + description + sample_payload shape.
    for entry in entries:
        assert entry["label"]
        assert entry["description"]
        assert isinstance(entry["sample_payload"], dict)
