"""Pin tests for the Step-8 record-mutation action handlers.

Each handler is exercised via the action registry. The tests rely
on the real origin services (contacts, leads, tasks, activities,
appointments, billing) writing to the test DB so the assertion is
"the row exists with the right shape" — same as what happens in
production.

Where the origin module isn't shipped yet (quotes, orders), the
test asserts the registered handler raises
``ActionNotImplemented``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.tasks.models import Task
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
)
from src.app.core.workflows.actions import records as records_module
from src.app.core.workflows.actions import (
    resolve as resolve_action,
)
from src.app.core.workflows.exceptions import ActionNotImplemented
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None
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
def _reset_action_registry():
    """Wipe + re-register so the test isolation pattern in the
    other workflows tests stays consistent. Step-8 register() runs
    automatically on module import so we just call it again here
    after _clear."""
    _clear_registry_for_tests()
    _register_builtins()
    records_module.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()
    records_module.register()


async def _make_contact(test_db, *, org_id, email="asha@example.com"):
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, email, phone) "
            "VALUES (:id, :org_id, :name, :email, :phone)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "name": "Asha Mehta",
            "email": email,
            "phone": "+919876543210",
        },
    )
    await test_db.commit()
    return contact_id


async def _make_lead(test_db, *, org_id, contact_id) -> Lead:
    lead = Lead(
        org_id=org_id,
        contact_id=contact_id,
        status=LeadStatus.active,
        pipeline_stage="qualified",
        source="manual",
    )
    test_db.add(lead)
    await test_db.commit()
    await test_db.refresh(lead)
    return lead


def _run_for(org_id, contact_id=None) -> _FakeRun:
    return _FakeRun(
        org_id=org_id,
        workflow_id=uuid.uuid4(),
        contact_id=contact_id,
        created_by_user_id=None,
    )


# ---------------------------------------------------------------------------
# record.update_contact_field
# ---------------------------------------------------------------------------


async def test_update_contact_field_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.update_contact_field")
    node = {
        "id": "uc",
        "type": "record.update_contact_field",
        "config": {
            "field_path": "tags",
            "value": ["vip", "newsletter"],
        },
    }
    context = {"contact": None, "trigger_payload": {}, "run_state": {}}

    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert result.output["contact_id"] == str(contact_id)

    refreshed = (
        await test_db.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one()
    assert refreshed.tags == ["vip", "newsletter"]


async def test_update_contact_field_target_missing(test_db, org_id):
    """No contact_id on run + no override → target_not_found."""
    run = _run_for(org_id, contact_id=None)
    handler = resolve_action("record.update_contact_field")
    node = {
        "id": "uc",
        "type": "record.update_contact_field",
        "config": {"field_path": "tags", "value": ["x"]},
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "target_not_found"


async def test_update_contact_field_validation_failed(test_db, org_id):
    """Missing field_path → validation_failed."""
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.update_contact_field")
    node = {
        "id": "uc",
        "type": "record.update_contact_field",
        "config": {"value": "x"},  # no field_path
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
# record.update_lead_field + update_lead_stage
# ---------------------------------------------------------------------------


async def test_update_lead_field_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.update_lead_field")
    node = {
        "id": "ul",
        "type": "record.update_lead_field",
        "config": {
            "field_path": "source",
            "value": "{{ trigger_payload.source }}",
            "lead_id": str(lead.id),
        },
    }
    context = {
        "contact": None,
        "trigger_payload": {"source": "AdWords-Diwali"},
        "run_state": {},
    }

    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    refreshed = (await test_db.execute(select(Lead).where(Lead.id == lead.id))).scalar_one()
    assert refreshed.source == "AdWords-Diwali"


async def test_update_lead_stage_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.update_lead_stage")
    node = {
        "id": "us",
        "type": "record.update_lead_stage",
        "config": {"pipeline_stage": "negotiation", "lead_id": str(lead.id)},
    }

    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={
                "contact": None,
                "trigger_payload": {},
                "run_state": {},
            },
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    refreshed = (await test_db.execute(select(Lead).where(Lead.id == lead.id))).scalar_one()
    assert refreshed.pipeline_stage == "negotiation"


# ---------------------------------------------------------------------------
# record.create_task — happy + variable resolution
# ---------------------------------------------------------------------------


async def test_create_task_happy_with_variable_render(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    run.created_by_user_id = uuid.uuid4()
    handler = resolve_action("record.create_task")
    node = {
        "id": "ct",
        "type": "record.create_task",
        "config": {
            "title": "Follow up with {{ contact.full_name }}",
            "due_in_days": 3,
            "priority": "high",
        },
    }
    context = {
        "contact": {"full_name": "Asha Mehta"},
        "trigger_payload": {},
        "run_state": {},
    }

    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context=context,
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert result.output["task_id"]
    assert "Asha Mehta" in result.output["task_title"]

    task = (
        await test_db.execute(select(Task).where(Task.id == uuid.UUID(result.output["task_id"])))
    ).scalar_one()
    assert task.title == "Follow up with Asha Mehta"


async def test_create_task_missing_title(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.create_task")
    node = {
        "id": "ct",
        "type": "record.create_task",
        "config": {"due_in_days": 1},
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"contact": None, "trigger_payload": {}, "run_state": {}},
    )
    assert result.skip_reason == "validation_failed"


# ---------------------------------------------------------------------------
# record.create_note
# ---------------------------------------------------------------------------


async def test_create_note_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    handler = resolve_action("record.create_note")
    node = {
        "id": "n1",
        "type": "record.create_note",
        "config": {"body": "Workflow followup for {{ contact.full_name }}"},
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={
                "contact": {"full_name": "Asha Mehta"},
                "trigger_payload": {},
                "run_state": {},
            },
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert "Asha Mehta" in result.output["note_body"]


# ---------------------------------------------------------------------------
# Placeholders raising ActionNotImplemented
# ---------------------------------------------------------------------------


async def test_create_quote_raises_action_not_implemented(test_db, org_id):
    run = _run_for(org_id)
    handler = resolve_action("record.create_quote")
    with pytest.raises(ActionNotImplemented) as exc:
        await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={"id": "q", "type": "record.create_quote", "config": {}},
            context={"contact": None, "trigger_payload": {}, "run_state": {}},
        )
    assert exc.value.action_type == "record.create_quote"


async def test_create_order_raises_action_not_implemented(test_db, org_id):
    run = _run_for(org_id)
    handler = resolve_action("record.create_order")
    with pytest.raises(ActionNotImplemented):
        await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={"id": "o", "type": "record.create_order", "config": {}},
            context={"contact": None, "trigger_payload": {}, "run_state": {}},
        )


# ---------------------------------------------------------------------------
# record.create_invoice
# ---------------------------------------------------------------------------


async def test_create_invoice_happy(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    run = _run_for(org_id, contact_id=contact_id)
    run.created_by_user_id = uuid.uuid4()
    handler = resolve_action("record.create_invoice")
    node = {
        "id": "inv",
        "type": "record.create_invoice",
        "config": {
            "notes": "Workflow-generated invoice for {{ contact.full_name }}",
            "items": [
                {
                    "description": "Consultation fee",
                    "quantity": 1,
                    "unit_price": 5000,
                    "tax_rate": 18,
                }
            ],
        },
    }
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node=node,
            context={
                "contact": {"full_name": "Asha Mehta"},
                "trigger_payload": {},
                "run_state": {},
            },
        )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert result.output["invoice_id"]
