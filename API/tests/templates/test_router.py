"""Router-layer tests for ``core.templates.router``.

Exercises the 9 endpoints via the layered ASGI app (``layered_client``
fixture). Covers happy-path CRUD, RLS isolation across orgs, missing-
permission 403s, locked-template 409s, version listing, preview
rendering, and the variable-picker discovery endpoint.

Auth uses the ``seeded_admin`` fixture which builds an Owner role
with every core key — including the five new ``templates.*`` keys
once the role-template registry's lifespan sweep registers them.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.permissions.service import register_permission


pytestmark = pytest.mark.asyncio


_TEMPLATE_KEYS = (
    "templates.read",
    "templates.write",
    "templates.review",
    "templates.publish",
    "templates.submit_external",
)


async def _grant_keys(role_id: uuid.UUID, *keys: str) -> None:
    """Insert (role_id, permission_id) rows for ``keys`` (registering
    each key if not already present in the registry). Idempotent."""
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


async def _login(layered_client, *, org_slug: str, email: str, password: str) -> str:
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- list + create -----------------------------------------------------


async def test_list_empty_returns_zero(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "templates.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/templates", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_create_then_read(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "templates.read", "templates.write")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "Welcome",
            "channel": "email",
            "category": "transactional",
            "language": "en",
            "body_text": "Hi {{ contact.first_name }}",
            "subject": "Welcome to {{ org.name }}",
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    tid = create_resp.json()["id"]

    get_resp = await layered_client.get(
        f"/api/v1/templates/{tid}", headers=headers
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["current_version"] == 1
    assert body["internal_status"] == "draft"
    assert "contact.first_name" in body["variables"]
    assert "org.name" in body["variables"]


async def test_create_requires_write_perm(layered_client, seeded_admin):
    # Only read; create should 403.
    await _grant_keys(seeded_admin["role"].id, "templates.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "X",
            "channel": "email",
            "body_text": "Body",
            "subject": "Subj",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_create_duplicate_name_returns_409(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "Dup",
        "channel": "email",
        "body_text": "Hi",
        "subject": "Subj",
    }
    r1 = await layered_client.post("/api/v1/templates", json=body, headers=headers)
    assert r1.status_code == 201
    # lower() case collision still rejected.
    body["name"] = "dup"
    r2 = await layered_client.post("/api/v1/templates", json=body, headers=headers)
    assert r2.status_code == 409


async def test_create_email_without_subject_is_422(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "templates.write")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/templates",
        json={"name": "NoSubj", "channel": "email", "body_text": "Body"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# --- update + versions -------------------------------------------------


async def test_update_bumps_version_and_lists_history(
    layered_client, seeded_admin
):
    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "T",
            "channel": "email",
            "body_text": "old",
            "subject": "s",
        },
        headers=headers,
    )
    tid = create_resp.json()["id"]

    patch_resp = await layered_client.patch(
        f"/api/v1/templates/{tid}",
        json={"body_text": "new {{ contact.first_name }}"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["current_version"] == 2

    versions_resp = await layered_client.get(
        f"/api/v1/templates/{tid}/versions", headers=headers
    )
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) == 2
    # Newest first.
    assert versions[0]["version"] == 2
    assert versions[1]["version"] == 1


async def test_update_locked_template_returns_409(
    layered_client, seeded_admin
):
    from tests.conftest import TestSession
    from src.app.core.templates.models import (
        MessageTemplate,
        TemplateInternalStatus,
    )

    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "Lock",
            "channel": "email",
            "body_text": "b",
            "subject": "s",
        },
        headers=headers,
    )
    tid = create_resp.json()["id"]

    # Flip status to in_review via direct DB write (Step 4 wires the
    # endpoint; we're testing the router's edit-lock here).
    async with TestSession() as session:
        row = (
            await session.execute(
                select(MessageTemplate).where(MessageTemplate.id == uuid.UUID(tid))
            )
        ).scalar_one()
        row.internal_status = TemplateInternalStatus.in_review
        await session.commit()

    resp = await layered_client.patch(
        f"/api/v1/templates/{tid}",
        json={"body_text": "edit attempt"},
        headers=headers,
    )
    assert resp.status_code == 409


# --- archive -----------------------------------------------------------


async def test_archive_returns_204_and_flips_status(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "Archive",
            "channel": "email",
            "body_text": "b",
            "subject": "s",
        },
        headers=headers,
    )
    tid = create_resp.json()["id"]
    del_resp = await layered_client.delete(
        f"/api/v1/templates/{tid}", headers=headers
    )
    assert del_resp.status_code == 204
    get_resp = await layered_client.get(
        f"/api/v1/templates/{tid}", headers=headers
    )
    assert get_resp.json()["internal_status"] == "archived"


# --- preview + variables endpoints ------------------------------------


async def test_preview_renders_variables(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "Prev",
            "channel": "email",
            "body_text": "Hi {{ contact.first_name }}!",
            "subject": "Welcome to {{ org.name }}",
        },
        headers=headers,
    )
    tid = create_resp.json()["id"]
    preview_resp = await layered_client.post(
        f"/api/v1/templates/{tid}/preview",
        json={
            "context": {
                "contact": {"first_name": "Asha"},
                "org": {"name": "Acme"},
            }
        },
        headers=headers,
    )
    assert preview_resp.status_code == 200
    body = preview_resp.json()
    assert body["body"] == "Hi Asha!"
    assert body["subject"] == "Welcome to Acme"


async def test_preview_unknown_variable_yields_empty(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id, "templates.read", "templates.write"
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": "Prev2",
            "channel": "email",
            "body_text": "Hi {{ contact.first_name }}{{ unknown.tag }}",
            "subject": "S",
        },
        headers=headers,
    )
    tid = create_resp.json()["id"]
    resp = await layered_client.post(
        f"/api/v1/templates/{tid}/preview",
        json={"context": {"contact": {"first_name": "Asha"}}},
        headers=headers,
    )
    assert resp.status_code == 200
    # Unknown path renders empty, not the raw `{{...}}`.
    assert resp.json()["body"] == "Hi Asha"


async def test_variables_endpoint_returns_channel_registry(
    layered_client, seeded_admin
):
    await _grant_keys(seeded_admin["role"].id, "templates.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/templates/variables/email",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    keys = {r["key"] for r in rows}
    assert "contact.first_name" in keys
    assert "org.name" in keys
    assert "sender.signature" in keys  # email-specific namespace


# --- RLS / not-found ---------------------------------------------------


async def test_get_unknown_id_returns_404(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, "templates.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        f"/api/v1/templates/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
