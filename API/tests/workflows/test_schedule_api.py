"""Pin tests for the Step-3 schedule HTTP layer.

Covers the validation table + cross-org guard + mass-assign shield +
If-Match protocol + pause/resume dedicated endpoints. Uses a
FastAPI ``TestClient`` bound to a scoped-org context so the router's
``require_permissions`` + ``_require_org_id`` succeed without real
JWT flow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_id(test_db):
    oid = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(oid), "name": "Demo", "slug": f"demo-{oid.hex[:6]}"},
    )
    await test_db.commit()
    return oid


@pytest_asyncio.fixture
async def workflow_id(test_db, org_id):
    """Seed an active workflow the schedule endpoints can attach to."""
    from src.app.core.workflows.models import Workflow, WorkflowStatus

    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph={
            "nodes": [{"id": "t1", "type": "trigger.lead_created"}],
            "edges": [],
        },
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf.id


@pytest_asyncio.fixture
async def client(test_db, org_id, monkeypatch):
    """FastAPI TestClient with the auth + org-context deps stubbed.

    We bypass the JWT / session lookup — the router only needs the
    request context populated with (org_id, user_id) and the
    permission-check dep to return truthy. That gives faithful
    coverage of the router logic without dragging in JWT + session
    fixtures per test."""
    from src.app import main as main_mod
    from src.app.core.auth import dependencies as auth_deps
    from src.app.core.workflows import router as wf_router_mod
    from src.app.shared import context as ctx_mod
    from src.app.shared import db as shared_db

    # Bind the DB session-maker used by the app to the test DB.
    bind = test_db.get_bind()
    fake_sessionmaker = async_sessionmaker(bind, expire_on_commit=False)
    monkeypatch.setattr(shared_db, "async_session", fake_sessionmaker)

    # Override get_db to yield the pytest test_db session so schedule
    # rows created by the endpoint are visible to test assertions.
    async def _override_get_db():
        yield test_db

    main_mod.app.dependency_overrides[shared_db.get_db] = _override_get_db

    # Stub out require_permissions — the router uses it as a dep
    # factory returning a User; a truthy sentinel is sufficient
    # because the endpoints never inspect the returned value.
    fake_user = object()

    def _fake_require_permissions(*_keys):
        def _dep():
            return fake_user

        return _dep

    monkeypatch.setattr(auth_deps, "require_permissions", _fake_require_permissions)
    monkeypatch.setattr(wf_router_mod, "require_permissions", _fake_require_permissions)

    # Stub the org-context read so the endpoints see the test org.
    class _Ctx:
        def __init__(self, org_id: uuid.UUID) -> None:
            self.org_id = org_id
            self.user_id = uuid.uuid4()

    monkeypatch.setattr(ctx_mod, "get_context", lambda: _Ctx(org_id))
    monkeypatch.setattr(wf_router_mod, "get_context", lambda: _Ctx(org_id))

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app),
        base_url="http://test",
    ) as c:
        yield c

    main_mod.app.dependency_overrides.pop(shared_db.get_db, None)


def _future(minutes: int = 5) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _past(minutes: int = 5) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_create_schedule_valid_returns_201(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "daily",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "daily"
    assert r.json()["active"] is True
    assert r.json()["schedule_kind"] == "daily"


async def test_get_single_returns_etag_header(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "etag-test",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    r = await client.get(f"/api/v1/schedules/{sched_id}")
    assert r.status_code == 200
    assert r.headers.get("etag") is not None
    # ETag format: UTC no-tz second-precision ISO.
    assert "+" not in r.headers["etag"]
    assert "." not in r.headers["etag"]


async def test_list_schedules_for_workflow(client, workflow_id):
    for i in range(2):
        await client.post(
            f"/api/v1/workflows/{workflow_id}/schedules",
            json={
                "name": f"s{i}",
                "schedule_kind": "daily",
                "config_json": {"time": "09:00"},
                "timezone": "UTC",
                "starts_at": _future(),
            },
        )
    r = await client.get(f"/api/v1/workflows/{workflow_id}/schedules")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_delete_schedule_returns_204_and_then_404(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "delete-me",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    r = await client.delete(f"/api/v1/schedules/{sched_id}")
    assert r.status_code == 204
    r = await client.get(f"/api/v1/schedules/{sched_id}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cross-org guard
# ---------------------------------------------------------------------------


async def test_create_cross_org_workflow_returns_404(client):
    """Attaching a schedule to a workflow the caller's org doesn't own
    → 404 (no info leak — matches "not found")."""
    r = await client.post(
        f"/api/v1/workflows/{uuid.uuid4()}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 404


async def test_get_cross_org_schedule_returns_404(client):
    r = await client.get(f"/api/v1/schedules/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_delete_cross_org_schedule_returns_404(client):
    r = await client.delete(f"/api/v1/schedules/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_pause_cross_org_schedule_returns_404(client):
    r = await client.post(f"/api/v1/schedules/{uuid.uuid4()}/pause")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Mass-assignment shield
# ---------------------------------------------------------------------------


async def test_create_rejects_runs_completed_field(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
            "runs_completed": 99,
        },
    )
    assert r.status_code == 422


async def test_create_rejects_org_id_field(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
            "org_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 422


async def test_patch_rejects_active_field(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    get_resp = await client.get(f"/api/v1/schedules/{sched_id}")
    etag = get_resp.headers["etag"]
    r = await client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"active": False},
        headers={"If-Match": etag},
    )
    assert r.status_code == 422


async def test_patch_rejects_next_run_at_field(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    etag = (await client.get(f"/api/v1/schedules/{sched_id}")).headers["etag"]
    r = await client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"next_run_at": _future(60)},
        headers={"If-Match": etag},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


async def test_create_past_starts_at_returns_422(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _past(),
        },
    )
    assert r.status_code == 422
    assert "past" in r.text.lower()


async def test_create_bogus_timezone_returns_422(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "Not/A/Zone",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 422


async def test_create_interval_below_5min_returns_422(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "interval",
            "config_json": {"every": 2, "unit": "minutes"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 422


async def test_create_cron_minute_star_returns_422(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "cron",
            "config_json": {"expression": "*/1 * * * *"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 422


async def test_create_end_before_start_returns_422(client, workflow_id):
    r = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(60),
            "end_at": _future(30),
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# If-Match protocol
# ---------------------------------------------------------------------------


async def test_patch_without_if_match_returns_428(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    r = await client.patch(f"/api/v1/schedules/{sched_id}", json={"name": "y"})
    assert r.status_code == 428


async def test_patch_stale_if_match_returns_409(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    r = await client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"name": "y"},
        headers={"If-Match": "1970-01-01T00:00:00"},
    )
    assert r.status_code == 409


async def test_patch_correct_if_match_returns_200(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]
    etag = (await client.get(f"/api/v1/schedules/{sched_id}")).headers["etag"]
    r = await client.patch(
        f"/api/v1/schedules/{sched_id}",
        json={"name": "renamed"},
        headers={"If-Match": etag},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


async def test_pause_and_resume_toggle_active(client, workflow_id):
    create = await client.post(
        f"/api/v1/workflows/{workflow_id}/schedules",
        json={
            "name": "x",
            "schedule_kind": "daily",
            "config_json": {"time": "09:00"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    sched_id = create.json()["id"]

    r = await client.post(f"/api/v1/schedules/{sched_id}/pause")
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["deactivation_reason"] == "manual"

    r = await client.post(f"/api/v1/schedules/{sched_id}/resume")
    assert r.status_code == 200
    assert r.json()["active"] is True
    assert r.json()["deactivation_reason"] is None


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


async def test_preview_cron_returns_5_fires(client):
    r = await client.post(
        "/api/v1/schedules/preview",
        json={
            "schedule_kind": "cron",
            "config_json": {"expression": "0 9 * * 1"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 200
    fires = r.json()["fires"]
    assert len(fires) == 5


async def test_preview_bad_cron_returns_422(client):
    r = await client.post(
        "/api/v1/schedules/preview",
        json={
            "schedule_kind": "cron",
            "config_json": {"expression": "*/1 * * * *"},
            "timezone": "UTC",
            "starts_at": _future(),
        },
    )
    assert r.status_code == 422
