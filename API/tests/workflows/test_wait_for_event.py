"""Pin tests for the Step-11 wait-for-event mechanism.

Covers: wait_for_event handler writes a tbl_workflow_event_waits
row + parks the run; matching event resumes the run; expired waits
are picked up by the sweep; cascade-delete on parent run cancel.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.workflows import (
    data_access as workflows_da,
)
from src.app.core.workflows.actions import (
    _clear_registry_for_tests,
    _register_builtins,
)
from src.app.core.workflows.actions import flow_control as flow_module
from src.app.core.workflows.actions import (
    resolve as resolve_action,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowEventWait,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)

pytestmark = pytest.mark.asyncio


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


async def _make_workflow(test_db, *, org_id) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"wf-{uuid.uuid4().hex[:6]}",
        status=WorkflowStatus.active,
        current_version=1,
        graph={
            "nodes": [
                {
                    "id": "t1",
                    "type": "trigger.lead_created",
                    "config": {"event_type": "lead.created"},
                },
                {"id": "wfe", "type": "flow_control.wait_for_event", "config": {}},
                {"id": "end_ok", "type": "flow.end", "config": {}},
                {"id": "end_to", "type": "flow.end", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "t1", "target": "wfe"},
                {"id": "e2", "source": "wfe", "target": "end_ok", "label": "event_received"},
                {"id": "e3", "source": "wfe", "target": "end_to", "label": "timeout"},
            ],
        },
        enabled_event_types=["lead.created"],
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


async def _make_run(test_db, *, org_id, workflow_id, contact_id=None) -> WorkflowRun:
    run = WorkflowRun(
        org_id=org_id,
        workflow_id=workflow_id,
        version=1,
        contact_id=contact_id,
        status=WorkflowRunStatus.running,
        current_node_id="wfe",
        state={},
    )
    test_db.add(run)
    await test_db.commit()
    await test_db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Handler parks run + writes wait row
# ---------------------------------------------------------------------------


async def test_wait_for_event_writes_wait_row_and_parks(test_db, org_id):
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_contacts (id, org_id, full_name) VALUES (:id, :org_id, :name)"),
        {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
    )
    await test_db.commit()
    wf = await _make_workflow(test_db, org_id=org_id)
    run = await _make_run(test_db, org_id=org_id, workflow_id=wf.id, contact_id=contact_id)

    handler = resolve_action("flow_control.wait_for_event")
    node = {
        "id": "wfe",
        "type": "flow_control.wait_for_event",
        "config": {
            "event_type": "quote.viewed",
            "max_wait_seconds": 7 * 24 * 60 * 60,
            "contact_match": True,
        },
    }
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node=node,
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )

    assert result.skip_reason is None
    assert result.output["event_type"] == "quote.viewed"

    waits = (
        (await test_db.execute(select(WorkflowEventWait).where(WorkflowEventWait.run_id == run.id)))
        .scalars()
        .all()
    )
    assert len(waits) == 1
    assert waits[0].event_type == "quote.viewed"
    assert waits[0].contact_id == contact_id

    await test_db.refresh(run)
    assert run.status == WorkflowRunStatus.pending
    assert run.next_step_at is not None


async def test_wait_for_event_invalid_event_type_rejected(test_db, org_id):
    wf = await _make_workflow(test_db, org_id=org_id)
    run = await _make_run(test_db, org_id=org_id, workflow_id=wf.id)
    handler = resolve_action("flow_control.wait_for_event")
    result = await handler(
        test_db,
        run=run,
        step_run=_FakeStepRun(),
        node={
            "id": "wfe",
            "type": "flow_control.wait_for_event",
            "config": {"max_wait_seconds": 3600},  # no event_type
        },
        context={"trigger_payload": {}, "run_state": {}, "contact": None},
    )
    assert result.skip_reason == "validation_failed"


# ---------------------------------------------------------------------------
# DAL: find_waits_for_event matches correctly
# ---------------------------------------------------------------------------


async def test_find_waits_matches_contact_and_wildcard(test_db, org_id):
    """A wait with contact_id=X matches only events for contact X.
    A wait with contact_id=NULL matches any event."""
    wf = await _make_workflow(test_db, org_id=org_id)
    contact_a = uuid.uuid4()
    contact_b = uuid.uuid4()
    for cid in (contact_a, contact_b):
        await test_db.execute(
            sql_text(
                "INSERT INTO tbl_contacts (id, org_id, full_name) VALUES (:id, :org_id, :name)"
            ),
            {"id": str(cid), "org_id": str(org_id), "name": "x"},
        )
    await test_db.commit()

    run_a = await _make_run(test_db, org_id=org_id, workflow_id=wf.id, contact_id=contact_a)
    run_wild = await _make_run(test_db, org_id=org_id, workflow_id=wf.id, contact_id=None)

    expires_at = datetime.now(UTC) + timedelta(hours=1)
    test_db.add_all(
        [
            WorkflowEventWait(
                org_id=org_id,
                run_id=run_a.id,
                node_id="wfe",
                event_type="quote.viewed",
                contact_id=contact_a,
                expires_at=expires_at,
            ),
            WorkflowEventWait(
                org_id=org_id,
                run_id=run_wild.id,
                node_id="wfe",
                event_type="quote.viewed",
                contact_id=None,
                expires_at=expires_at,
            ),
        ]
    )
    await test_db.commit()

    # Event for contact_a → both waits match (specific + wildcard).
    matches = await workflows_da.find_waits_for_event(
        test_db,
        org_id=org_id,
        event_type="quote.viewed",
        contact_id=contact_a,
    )
    matched_runs = {w.run_id for w in matches}
    assert run_a.id in matched_runs
    assert run_wild.id in matched_runs

    # Event for contact_b → only the wildcard wait matches.
    matches_b = await workflows_da.find_waits_for_event(
        test_db,
        org_id=org_id,
        event_type="quote.viewed",
        contact_id=contact_b,
    )
    matched_runs_b = {w.run_id for w in matches_b}
    assert run_wild.id in matched_runs_b
    assert run_a.id not in matched_runs_b


async def test_find_waits_excludes_expired(test_db, org_id):
    """Expired waits don't surface — partial-index predicate filters
    them out."""
    wf = await _make_workflow(test_db, org_id=org_id)
    run = await _make_run(test_db, org_id=org_id, workflow_id=wf.id)
    test_db.add(
        WorkflowEventWait(
            org_id=org_id,
            run_id=run.id,
            node_id="wfe",
            event_type="quote.viewed",
            contact_id=None,
            expires_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await test_db.commit()

    matches = await workflows_da.find_waits_for_event(
        test_db,
        org_id=org_id,
        event_type="quote.viewed",
        contact_id=None,
    )
    assert all(w.run_id != run.id for w in matches)


# ---------------------------------------------------------------------------
# Sweep: list_expired_waits returns waits past expires_at
# ---------------------------------------------------------------------------


async def test_list_expired_waits_returns_past_due(test_db, org_id):
    wf = await _make_workflow(test_db, org_id=org_id)
    run = await _make_run(test_db, org_id=org_id, workflow_id=wf.id)

    expired = WorkflowEventWait(
        org_id=org_id,
        run_id=run.id,
        node_id="wfe",
        event_type="quote.viewed",
        contact_id=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    not_expired = WorkflowEventWait(
        org_id=org_id,
        run_id=run.id,
        node_id="wfe2",
        event_type="quote.viewed",
        contact_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    test_db.add_all([expired, not_expired])
    await test_db.commit()

    rows = await workflows_da.list_expired_waits(test_db)
    ids = {w.id for w in rows}
    assert expired.id in ids
    assert not_expired.id not in ids


# ---------------------------------------------------------------------------
# Cascade delete on parent run
# ---------------------------------------------------------------------------


async def test_cascade_delete_when_parent_run_deleted(test_db, org_id):
    """tbl_workflow_event_waits.run_id has ON DELETE CASCADE.
    Deleting the parent run cleans up the wait row."""
    wf = await _make_workflow(test_db, org_id=org_id)
    run = await _make_run(test_db, org_id=org_id, workflow_id=wf.id)
    test_db.add(
        WorkflowEventWait(
            org_id=org_id,
            run_id=run.id,
            node_id="wfe",
            event_type="quote.viewed",
            contact_id=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await test_db.commit()

    await test_db.delete(run)
    await test_db.commit()

    remaining = (
        (await test_db.execute(select(WorkflowEventWait).where(WorkflowEventWait.run_id == run.id)))
        .scalars()
        .all()
    )
    assert remaining == []
