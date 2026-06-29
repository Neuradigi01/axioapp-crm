"""Pin tests for the Step-10 tagging action handlers."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
    resolve as resolve_action,
)
from src.app.core.workflows.actions import tagging as tagging_module
from src.app.core.workflows.exceptions import ActionNotImplemented
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _FakeStepRun:
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
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
    tagging_module.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()
    tagging_module.register()


async def _make_contact(test_db, *, org_id, tags=None):
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, tags) "
            "VALUES (:id, :org_id, :name, :tags)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "name": "Asha",
            "tags": tags or [],
        },
    )
    await test_db.commit()
    return contact_id


async def _make_lead(test_db, *, org_id, contact_id, score=10):
    lead = Lead(
        org_id=org_id,
        contact_id=contact_id,
        status=LeadStatus.active,
        pipeline_stage="new",
        source="manual",
        lead_score=score,
    )
    test_db.add(lead)
    await test_db.commit()
    await test_db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# add_tag
# ---------------------------------------------------------------------------


async def test_add_tag_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    handler = resolve_action("tagging.add_tag")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "t",
        "type": "tagging.add_tag",
        "config": {"tag": "vip", "target": "contact"},
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
    assert result.output["added"] is True
    contact = (
        await test_db.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one()
    assert "vip" in contact.tags


async def test_add_tag_idempotent(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id, tags=["vip"])
    handler = resolve_action("tagging.add_tag")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"id": "t", "type": "tagging.add_tag", "config": {"tag": "vip"}}
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
    assert result.output["added"] is False


# ---------------------------------------------------------------------------
# remove_tag
# ---------------------------------------------------------------------------


async def test_remove_tag_silent_on_missing(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id, tags=["other"])
    handler = resolve_action("tagging.remove_tag")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"id": "t", "type": "tagging.remove_tag", "config": {"tag": "vip"}}
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
    assert result.output["removed"] is False


async def test_remove_tag_present(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id, tags=["vip", "newsletter"])
    handler = resolve_action("tagging.remove_tag")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {"id": "t", "type": "tagging.remove_tag", "config": {"tag": "vip"}}
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
    assert result.output["removed"] is True
    contact = (
        await test_db.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one()
    assert "vip" not in contact.tags
    assert "newsletter" in contact.tags


# ---------------------------------------------------------------------------
# set_lead_score
# ---------------------------------------------------------------------------


async def test_set_lead_score_set(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id, score=10)
    handler = resolve_action("tagging.set_lead_score")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "s",
        "type": "tagging.set_lead_score",
        "config": {"operation": "set", "value": 50, "lead_id": str(lead.id)},
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
    assert result.output["new_score"] == 50


async def test_set_lead_score_increment(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id, score=10)
    handler = resolve_action("tagging.set_lead_score")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "s",
        "type": "tagging.set_lead_score",
        "config": {"operation": "increment", "value": 15, "lead_id": str(lead.id)},
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
    assert result.output["new_score"] == 25
    assert result.output["prior_score"] == 10


async def test_set_lead_score_decrement_clamps_at_zero(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id, score=5)
    handler = resolve_action("tagging.set_lead_score")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "s",
        "type": "tagging.set_lead_score",
        "config": {"operation": "decrement", "value": 20, "lead_id": str(lead.id)},
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
    assert result.output["new_score"] == 0


async def test_set_lead_score_crossing_threshold_publishes_event(
    test_db, org_id
):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id, score=70)
    handler = resolve_action("tagging.set_lead_score")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "s",
        "type": "tagging.set_lead_score",
        "config": {
            "operation": "increment",
            "value": 10,  # 70 → 80, crosses 75
            "lead_id": str(lead.id),
            "threshold": 75,
        },
    }
    fake_publish = AsyncMock()
    with patch("src.app.core.events.bus.publish", new=fake_publish):
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
    assert result.output["threshold_crossed"] == "up"
    fake_publish.assert_awaited_once()
    args, kwargs = fake_publish.await_args
    assert args[0] == "lead.score_threshold"


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


async def test_add_to_list_raises_action_not_implemented(test_db, org_id):
    handler = resolve_action("tagging.add_to_list")
    with pytest.raises(ActionNotImplemented):
        await handler(
            test_db,
            run=_FakeRun(org_id=org_id, workflow_id=uuid.uuid4()),
            step_run=_FakeStepRun(),
            node={
                "id": "l",
                "type": "tagging.add_to_list",
                "config": {"group_id": str(uuid.uuid4())},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )


async def test_remove_from_list_raises_action_not_implemented(test_db, org_id):
    handler = resolve_action("tagging.remove_from_list")
    with pytest.raises(ActionNotImplemented):
        await handler(
            test_db,
            run=_FakeRun(org_id=org_id, workflow_id=uuid.uuid4()),
            step_run=_FakeStepRun(),
            node={
                "id": "l",
                "type": "tagging.remove_from_list",
                "config": {"group_id": str(uuid.uuid4())},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
