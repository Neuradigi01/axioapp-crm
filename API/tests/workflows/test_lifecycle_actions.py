"""Pin tests for the Step-10 lifecycle action handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
)
from src.app.core.workflows.actions import lifecycle as lifecycle_module
from src.app.core.workflows.actions import (
    resolve as resolve_action,
)
from src.app.core.workflows.exceptions import ActionNotImplemented
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeRun:
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    trigger_payload: dict | None = None
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
    lifecycle_module.register()
    yield
    _clear_registry_for_tests()
    _register_builtins()
    lifecycle_module.register()


async def _make_contact(test_db, *, org_id):
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name, email) "
            "VALUES (:id, :org_id, :name, :email)"
        ),
        {
            "id": str(contact_id),
            "org_id": str(org_id),
            "name": "Asha",
            "email": "asha@example.com",
        },
    )
    await test_db.commit()
    return contact_id


async def _make_lead(test_db, *, org_id, contact_id):
    lead = Lead(
        org_id=org_id,
        contact_id=contact_id,
        status=LeadStatus.active,
        pipeline_stage="new",
        source="manual",
    )
    test_db.add(lead)
    await test_db.commit()
    await test_db.refresh(lead)
    return lead


async def _make_workflow(
    test_db,
    *,
    org_id,
    name="Target",
    status=WorkflowStatus.active,
    re_enroll=WorkflowReEnrollmentRule.never,
):
    wf = Workflow(
        org_id=org_id,
        name=name,
        status=status,
        current_version=1,
        graph={
            "nodes": [
                {
                    "id": "t1",
                    "type": "trigger.manual",
                    "config": {"event_type": "manual"},
                },
                {"id": "end", "type": "flow.end", "config": {}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "end"}],
        },
        enabled_event_types=["manual"],
        re_enrollment_rule=re_enroll,
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# mark_converted + mark_unsubscribed
# ---------------------------------------------------------------------------


async def test_mark_converted_flips_lead_to_won(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    lead = await _make_lead(test_db, org_id=org_id, contact_id=contact_id)
    handler = resolve_action("lifecycle.mark_converted")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    node = {
        "id": "mc",
        "type": "lifecycle.mark_converted",
        "config": {"lead_id": str(lead.id)},
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
    refreshed = (await test_db.execute(select(Lead).where(Lead.id == lead.id))).scalar_one()
    assert refreshed.status == LeadStatus.won


async def test_mark_unsubscribed_flips_email_opt_out(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    handler = resolve_action("lifecycle.mark_unsubscribed")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={
                "id": "u",
                "type": "lifecycle.mark_unsubscribed",
                "config": {},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason is None
    contact = (await test_db.execute(select(Contact).where(Contact.id == contact_id))).scalar_one()
    assert contact.email_opt_out is True
    assert contact.email_opt_out_at is not None


# ---------------------------------------------------------------------------
# enroll_in_workflow + dedupe by re-enrollment rule
# ---------------------------------------------------------------------------


async def test_enroll_in_workflow_creates_new_run(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    target_wf = await _make_workflow(test_db, org_id=org_id)
    handler = resolve_action("lifecycle.enroll_in_workflow")
    run = _FakeRun(
        org_id=org_id,
        workflow_id=uuid.uuid4(),
        contact_id=contact_id,
        trigger_payload={"source": "test"},
    )

    from src.app.core.workflows import engine as workflows_engine

    token = set_context(RequestContext(org_id=org_id))
    try:
        with patch.object(workflows_engine, "_schedule_process_step"):
            result = await handler(
                test_db,
                run=run,
                step_run=_FakeStepRun(),
                node={
                    "id": "e",
                    "type": "lifecycle.enroll_in_workflow",
                    "config": {"workflow_id": str(target_wf.id)},
                },
                context={
                    "trigger_payload": {"source": "test"},
                    "run_state": {},
                    "contact": None,
                },
            )
    finally:
        reset_context(token)

    assert result.skip_reason is None
    assert result.output["enrolled_workflow_id"] == str(target_wf.id)
    rows = (
        (await test_db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == target_wf.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].contact_id == contact_id


async def test_enroll_in_workflow_dedupes_under_once_rule(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    target_wf = await _make_workflow(
        test_db,
        org_id=org_id,
        re_enroll=WorkflowReEnrollmentRule.once,
    )
    # Seed a prior run for the contact.
    test_db.add(
        WorkflowRun(
            org_id=org_id,
            workflow_id=target_wf.id,
            version=1,
            contact_id=contact_id,
            trigger_event_id="prior",
            status=WorkflowRunStatus.completed,
            current_node_id=None,
            state={},
        )
    )
    await test_db.commit()

    handler = resolve_action("lifecycle.enroll_in_workflow")
    run = _FakeRun(
        org_id=org_id,
        workflow_id=uuid.uuid4(),
        contact_id=contact_id,
        trigger_payload={},
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={
                "id": "e",
                "type": "lifecycle.enroll_in_workflow",
                "config": {"workflow_id": str(target_wf.id)},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason == "dedupe_once"


async def test_enroll_in_workflow_refuses_non_active_target(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    paused = await _make_workflow(
        test_db,
        org_id=org_id,
        name="PausedTarget",
        status=WorkflowStatus.paused,
    )
    handler = resolve_action("lifecycle.enroll_in_workflow")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={
                "id": "e",
                "type": "lifecycle.enroll_in_workflow",
                "config": {"workflow_id": str(paused.id)},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.skip_reason == "validation_failed"


# ---------------------------------------------------------------------------
# remove_from_workflow
# ---------------------------------------------------------------------------


async def test_remove_from_workflow_cancels_active_runs(test_db, org_id):
    contact_id = await _make_contact(test_db, org_id=org_id)
    target_wf = await _make_workflow(test_db, org_id=org_id)
    # Two active runs + one completed (should not be touched).
    for status in (
        WorkflowRunStatus.pending,
        WorkflowRunStatus.running,
        WorkflowRunStatus.completed,
    ):
        test_db.add(
            WorkflowRun(
                org_id=org_id,
                workflow_id=target_wf.id,
                version=1,
                contact_id=contact_id,
                trigger_event_id=f"ev-{status.value}",
                status=status,
                current_node_id="t1",
                state={},
            )
        )
    await test_db.commit()

    handler = resolve_action("lifecycle.remove_from_workflow")
    run = _FakeRun(org_id=org_id, workflow_id=uuid.uuid4(), contact_id=contact_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await handler(
            test_db,
            run=run,
            step_run=_FakeStepRun(),
            node={
                "id": "r",
                "type": "lifecycle.remove_from_workflow",
                "config": {"workflow_id": str(target_wf.id)},
            },
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
    finally:
        reset_context(token)
    assert result.output["canceled_runs"] == 2
    canceled_rows = (
        (
            await test_db.execute(
                select(WorkflowRun).where(
                    WorkflowRun.workflow_id == target_wf.id,
                    WorkflowRun.status == WorkflowRunStatus.canceled,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(canceled_rows) == 2


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


async def test_block_contact_raises_action_not_implemented(test_db, org_id):
    handler = resolve_action("lifecycle.block_contact")
    with pytest.raises(ActionNotImplemented):
        await handler(
            test_db,
            run=_FakeRun(org_id=org_id, workflow_id=uuid.uuid4()),
            step_run=_FakeStepRun(),
            node={"id": "b", "type": "lifecycle.block_contact", "config": {}},
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )


async def test_archive_contact_raises_action_not_implemented(test_db, org_id):
    handler = resolve_action("lifecycle.archive_contact")
    with pytest.raises(ActionNotImplemented):
        await handler(
            test_db,
            run=_FakeRun(org_id=org_id, workflow_id=uuid.uuid4()),
            step_run=_FakeStepRun(),
            node={"id": "a", "type": "lifecycle.archive_contact", "config": {}},
            context={"trigger_payload": {}, "run_state": {}, "contact": None},
        )
