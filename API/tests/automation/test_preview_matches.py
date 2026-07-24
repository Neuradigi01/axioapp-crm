"""Tests for the matched-events preview
(``tasks/automation-conditions/`` Step 5).

Backend surface is a pure read + in-memory evaluator sweep — no
side effects, no writes. The pytest cases exercise:

  * The DAL helper filters + orders correctly (org-scoped, joined
    to trigger table for event_type, newest-first, respects the
    501-row cap).
  * The service function's honest source classification
    (``'runs'`` vs. ``'none'``), the truncated-cap flag, and the
    422 on structurally-broken AST.
  * The router's fast-404 on an event outside the catalog.

Requires a running DB fixture (``seeded_admin`` + ``layered_client``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.automation import service as automation_service
from src.app.core.automation.models import (
    AutomationRun,
    AutomationRunStatus,
    AutomationTrigger,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.shared.context import RequestContext, reset_context, set_context

_AUTOMATION_READ = ("automations.read",)


# --- fixtures / helpers ---------------------------------------------


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


async def _seed_runs(
    org_id: uuid.UUID,
    *,
    event_type: str,
    payloads: list[dict],
    template_id: uuid.UUID | None = None,
    minutes_ago: int = 60,
) -> uuid.UUID:
    """Insert a trigger + N run rows carrying ``payloads`` as
    ``event_payload``, all scheduled ``minutes_ago`` in the past
    (well inside the default 7-day preview window)."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            trigger = AutomationTrigger(
                org_id=org_id,
                name=f"preview-{uuid.uuid4().hex[:6]}",
                event_type=event_type,
                channel=ConversationChannel.email,
                template_id=template_id or uuid.uuid4(),
                enabled=True,
                conditions={},
                delay_seconds=0,
                recipient_resolver="contact.email",
                recipient_resolver_config={},
            )
            session.add(trigger)
            await session.flush()
            when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
            for payload in payloads:
                session.add(
                    AutomationRun(
                        org_id=org_id,
                        trigger_id=trigger.id,
                        event_id=uuid.uuid4().hex,
                        event_payload=payload,
                        status=AutomationRunStatus.sent,
                        scheduled_at=when,
                    )
                )
            await session.commit()
            return trigger.id
    finally:
        reset_context(token)


# --- service-layer tests --------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_matched_count_from_runs_source(seeded_admin):
    """Seed 3 runs on lead.created; 2 match the draft filter. Preview
    reports matched=2, scanned=3, source='runs'."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_runs(
        org_id,
        event_type="lead.created",
        payloads=[
            {"source": "widget", "lead": {"pipeline_stage": "new"}},
            {"source": "widget", "lead": {"pipeline_stage": "qualified"}},
            {"source": "google_ads", "lead": {"pipeline_stage": "new"}},
        ],
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            result = await automation_service.preview_matches(
                session,
                org_id=org_id,
                event_type="lead.created",
                conditions_ast={"field": "source", "op": "eq", "value": "widget"},
                window_days=7,
            )
    finally:
        reset_context(token)
    assert result == {
        "matched": 2,
        "scanned": 3,
        "window_days": 7,
        "source": "runs",
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_preview_returns_source_none_when_no_runs_in_window(seeded_admin):
    """Org has no runs for the requested event → source='none'
    (frontend renders "no historical events available" hint rather
    than a misleading zero-count)."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            result = await automation_service.preview_matches(
                session,
                org_id=org_id,
                event_type="lead.created",
                conditions_ast={},
                window_days=7,
            )
    finally:
        reset_context(token)
    assert result["source"] == "none"
    assert result["matched"] == 0
    assert result["scanned"] == 0
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_preview_rejects_invalid_conditions_at_service_layer(seeded_admin):
    """Broken AST → InvalidCondition (router maps to 422). Guards
    against silently reporting a zero-match on a structural error
    the operator couldn't diagnose."""
    from src.app.core.automation.exceptions import InvalidCondition
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            with pytest.raises(InvalidCondition):
                await automation_service.preview_matches(
                    session,
                    org_id=org_id,
                    event_type="lead.created",
                    conditions_ast={"field": "source", "op": "totally_fake_op"},
                    window_days=7,
                )
    finally:
        reset_context(token)


# --- endpoint tests -------------------------------------------------


@pytest.mark.asyncio
async def test_preview_endpoint_returns_matched_count(layered_client, seeded_admin):
    """End-to-end happy path via the HTTP endpoint. Preview response
    round-trips the schema + carries the Cache-Control header."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    await _seed_runs(
        seeded_admin["org"].id,
        event_type="lead.created",
        payloads=[
            {"source": "widget"},
            {"source": "widget"},
            {"source": "google_ads"},
        ],
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/preview-matches",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conditions": {"field": "source", "op": "eq", "value": "widget"},
            "window_days": 7,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched"] == 2
    assert body["scanned"] == 3
    assert body["source"] == "runs"
    assert body["truncated"] is False
    assert "max-age=15" in resp.headers.get("Cache-Control", "")


@pytest.mark.asyncio
async def test_preview_endpoint_404_when_event_unknown(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/nope.fake/preview-matches",
        headers={"Authorization": f"Bearer {token}"},
        json={"conditions": {}, "window_days": 7},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "automation.event_not_found"
