"""Pin tests for the Step-11 flow-control action handlers (excluding
``wait_for_event`` which has its own file). Covers wait / ab_split /
goal / call_webhook / notify_user / log_internal_note."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
)
from src.app.core.workflows.actions import flow_control as flow_module
from src.app.core.workflows.actions import (
    resolve as resolve_action,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_by_user_id: uuid.UUID | None = None


@dataclass
class _FakeStepRun:
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {
            "id": str(org_id),
            "name": "Demo",
            "slug": f"demo-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


@pytest.fixture(autouse=True)
def _reset_registry():
    _clear_registry_for_tests()
    _register_builtins()
    flow_module.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()
    flow_module.register()


# ---------------------------------------------------------------------------
# flow_control.wait
# ---------------------------------------------------------------------------


async def test_wait_handler_returns_noop(test_db, org_id):
    """The handler itself is a no-op; the engine's _advance does the
    parking. We just assert the handler returns an empty
    ActionResult."""
    handler = resolve_action("flow_control.wait")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "w",
        "type": "flow_control.wait",
        "config": {"duration_seconds": 3600},
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason is None
    assert result.next_edge_label is None


# ---------------------------------------------------------------------------
# flow_control.ab_split
# ---------------------------------------------------------------------------


async def test_ab_split_deterministic_per_run_node(test_db, org_id):
    """Same (run_id, node_id) seed → same edge every time."""
    handler = resolve_action("flow_control.ab_split")
    run_id = uuid.uuid4()
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), id=run_id)
    node = {"id": "ab1", "type": "flow_control.ab_split", "config": {}}

    first = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    second = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert first.next_edge_label == second.next_edge_label
    assert first.next_edge_label in ("a", "b")


async def test_ab_split_honors_weighted_config(test_db, org_id):
    """A 100/0 weight ALWAYS picks 'a'; 0/100 ALWAYS picks 'b'."""
    handler = resolve_action("flow_control.ab_split")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())

    node_a = {
        "id": "ab",
        "type": "flow_control.ab_split",
        "config": {"weights": [100, 0]},
    }
    result_a = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node_a,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result_a.next_edge_label == "a"

    node_b = {
        "id": "ab",
        "type": "flow_control.ab_split",
        "config": {"weights": [0, 100]},
    }
    result_b = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node_b,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result_b.next_edge_label == "b"


# ---------------------------------------------------------------------------
# flow_control.goal
# ---------------------------------------------------------------------------


async def test_goal_handler_returns_terminal(test_db, org_id):
    """Goal marker returns next_edge_label=None. The engine's
    _advance treats no-outbound as terminal + sets goal_reached
    when workflow.goal_node_id == executed_node."""
    handler = resolve_action("flow_control.goal")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {"id": "goal", "type": "flow_control.goal", "config": {}}
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.next_edge_label is None
    assert result.skip_reason is None
    assert result.output.get("goal_marker") is True


# ---------------------------------------------------------------------------
# flow_control.call_webhook
# ---------------------------------------------------------------------------


async def test_call_webhook_happy_2xx(test_db, org_id):
    handler = resolve_action("flow_control.call_webhook")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "wh",
        "type": "flow_control.call_webhook",
        "config": {
            "url": "https://example.com/hook",
            "body_template": '{"contact_id": "{{ contact.id }}"}',
        },
    }
    context = {
        "contact": {"id": "abc"},
        "trigger_payload": {},
        "run_state": {},
    }

    class _FakeResponse:
        status_code = 200
        text = '{"ok": true}'

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content, headers):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeClient):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )

    assert result.skip_reason is None
    assert result.output["webhook_status"] == 200


async def test_call_webhook_5xx_skips_by_default(test_db, org_id):
    handler = resolve_action("flow_control.call_webhook")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "wh",
        "type": "flow_control.call_webhook",
        "config": {
            "url": "https://example.com/hook",
            "body_template": "{}",
        },
    }

    class _FakeResponse:
        status_code = 503
        text = "service unavailable"

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content, headers):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeClient):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )

    assert result.skip_reason == "webhook_failed"
    assert "503" in result.output["skip_reason"]


async def test_call_webhook_invalid_url_rejected(test_db, org_id):
    handler = resolve_action("flow_control.call_webhook")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "wh",
        "type": "flow_control.call_webhook",
        "config": {"url": "http://insecure.example.com", "body_template": "{}"},
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "validation_failed"


# ---------------------------------------------------------------------------
# flow_control.notify_user
# ---------------------------------------------------------------------------


async def test_notify_user_specific_user_calls_notifications(test_db, org_id):
    handler = resolve_action("flow_control.notify_user")
    target_user = uuid.uuid4()
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "n",
        "type": "flow_control.notify_user",
        "config": {
            "recipient": "specific_user",
            "user_id": str(target_user),
            "title": "Hot lead from {{ contact.full_name }}",
            "type": "workflow.hot_lead",
        },
    }
    context = {
        "contact": {"full_name": "Asha Mehta"},
        "trigger_payload": {},
        "run_state": {},
    }

    fake_notify = AsyncMock()
    with patch("src.app.core.notifications.service.notify", new=fake_notify):
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )

    assert result.skip_reason is None
    fake_notify.assert_awaited_once()
    kwargs = fake_notify.await_args.kwargs
    assert kwargs["user_id"] == target_user
    assert "Asha Mehta" in kwargs["title"]


async def test_notify_user_no_recipient_skips(test_db, org_id):
    handler = resolve_action("flow_control.notify_user")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4())
    node = {
        "id": "n",
        "type": "flow_control.notify_user",
        "config": {"recipient": "specific_user"},  # no user_id
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "target_not_found"


# ---------------------------------------------------------------------------
# flow_control.log_internal_note
# ---------------------------------------------------------------------------


async def test_log_internal_note_writes_timeline_entry(test_db, org_id):
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_contacts (id, org_id, full_name) VALUES (:id, :org_id, :name)"),
        {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
    )
    await test_db.commit()

    handler = resolve_action("flow_control.log_internal_note")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "note",
        "type": "flow_control.log_internal_note",
        "config": {"body": "Workflow noticed VIP attention required"},
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert result.output["is_internal"] is True

    rows = (
        await test_db.execute(
            sql_text(
                "SELECT type, payload FROM tbl_activities "
                "WHERE org_id = :org_id AND entity_type = 'contact' "
                "AND entity_id = :contact_id ORDER BY created_at DESC LIMIT 1"
            ),
            {"org_id": str(org_id), "contact_id": str(contact_id)},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == "note"
    payload = rows[0][1]
    assert payload.get("is_internal") is True
