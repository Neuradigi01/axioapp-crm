"""Router-layer tests for ``core.workflows.router``.

Exercises the twelve endpoints via the layered ASGI app
(``layered_client`` fixture) — happy-path CRUD, permission gating,
status transitions, clone, folder CRUD, error mapping.

Auth uses ``seeded_admin`` from conftest. Workflow + template
permission keys are granted per-test via ``_grant_keys`` so each
scenario is hermetic.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    register_action,
)


pytestmark = pytest.mark.asyncio


_WORKFLOW_KEYS = (
    "workflows.read",
    "workflows.write",
    "workflows.activate",
    "workflows.clone",
)


@pytest.fixture(autouse=True)
def _seed_action_registry():
    """Register ``send.email`` so the graph validator passes the
    action-registry check during router tests."""
    _clear_registry_for_tests()
    register_action("send.email", lambda: object())
    yield
    _clear_registry_for_tests()


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


async def _seed_template(layered_client, headers) -> str:
    """Create an email template; send nodes in the workflow graph
    reference it by id."""
    resp = await layered_client.post(
        "/api/v1/templates",
        json={
            "name": f"WfTpl-{uuid.uuid4().hex[:6]}",
            "channel": "email",
            "category": "transactional",
            "body_text": "Hi {{ contact.full_name }}",
            "subject": "Hello",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _valid_graph(template_id: str) -> dict:
    return {
        "nodes": [
            {
                "id": "t1",
                "type": "trigger.lead_created",
                "position": {"x": 0, "y": 0},
                "config": {"event_type": "lead.created"},
            },
            {
                "id": "s1",
                "type": "send.email",
                "position": {"x": 200, "y": 0},
                "config": {"template_id": template_id},
            },
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "s1"},
        ],
    }


# --- CRUD happy paths ----------------------------------------------------


async def test_create_workflow_201(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
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
    template_id = await _seed_template(layered_client, headers)

    resp = await layered_client.post(
        "/api/v1/workflows",
        json={
            "name": "Welcome",
            "graph": _valid_graph(template_id),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["current_version"] == 1
    assert body["enabled_event_types"] == ["lead.created"]


async def test_create_workflow_invalid_graph_422(layered_client, seeded_admin):
    """A graph missing the trigger node returns 422 with the
    ``reason`` field populated."""
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        "/api/v1/workflows",
        json={
            "name": "Broken",
            "graph": {
                "nodes": [
                    {
                        "id": "s1",
                        "type": "send.email",
                        "position": {"x": 0, "y": 0},
                        "config": {
                            "template_id": "00000000-0000-0000-0000-000000000001"
                        },
                    }
                ],
                "edges": [],
            },
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_graph"
    assert "trigger" in detail["reason"].lower()


async def test_create_workflow_403_without_write(layered_client, seeded_admin):
    """Caller with `workflows.read` only is refused on POST."""
    await _grant_keys(seeded_admin["role"].id, "workflows.read")
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/workflows",
        json={
            "name": "Welcome",
            "graph": {"nodes": [], "edges": []},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


async def test_list_workflows_filters_by_status(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
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
    template_id = await _seed_template(layered_client, headers)

    create_resp = await layered_client.post(
        "/api/v1/workflows",
        json={"name": "Draft One", "graph": _valid_graph(template_id)},
        headers=headers,
    )
    assert create_resp.status_code == 201

    resp = await layered_client.get(
        "/api/v1/workflows?status=draft", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert all(it["status"] == "draft" for it in body["items"])

    resp_active = await layered_client.get(
        "/api/v1/workflows?status=active", headers=headers
    )
    assert resp_active.status_code == 200
    assert resp_active.json()["total"] == 0


# --- Status transitions + clone -----------------------------------------


async def test_activate_workflow(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
        "workflows.activate",
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
    template_id = await _seed_template(layered_client, headers)

    create_resp = await layered_client.post(
        "/api/v1/workflows",
        json={"name": "Welcome", "graph": _valid_graph(template_id)},
        headers=headers,
    )
    workflow_id = create_resp.json()["id"]

    resp = await layered_client.post(
        f"/api/v1/workflows/{workflow_id}/activate",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"


async def test_clone_creates_fresh_draft(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
        "workflows.clone",
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
    template_id = await _seed_template(layered_client, headers)

    src_resp = await layered_client.post(
        "/api/v1/workflows",
        json={"name": "Original", "graph": _valid_graph(template_id)},
        headers=headers,
    )
    src_id = src_resp.json()["id"]

    clone_resp = await layered_client.post(
        f"/api/v1/workflows/{src_id}/clone",
        json={"name": "Clone of Original"},
        headers=headers,
    )
    assert clone_resp.status_code == 201, clone_resp.text
    body = clone_resp.json()
    assert body["name"] == "Clone of Original"
    assert body["status"] == "draft"
    assert body["current_version"] == 1
    assert body["id"] != src_id


# --- Folder CRUD --------------------------------------------------------


async def test_delete_folder_409_when_non_empty(layered_client, seeded_admin):
    await _grant_keys(
        seeded_admin["role"].id,
        "workflows.read",
        "workflows.write",
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
    template_id = await _seed_template(layered_client, headers)

    folder_resp = await layered_client.post(
        "/api/v1/workflows/folders",
        json={"name": "Sales"},
        headers=headers,
    )
    assert folder_resp.status_code == 201, folder_resp.text
    folder_id = folder_resp.json()["id"]

    await layered_client.post(
        "/api/v1/workflows",
        json={
            "name": "Inside",
            "folder_id": folder_id,
            "graph": _valid_graph(template_id),
        },
        headers=headers,
    )

    del_resp = await layered_client.delete(
        f"/api/v1/workflows/folders/{folder_id}",
        headers=headers,
    )
    assert del_resp.status_code == 409, del_resp.text
    detail = del_resp.json()["detail"]
    assert detail["code"] == "folder_has_workflows"
    assert detail["count"] == 1
