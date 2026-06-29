"""Pin tests for the Step-5 bus → engine bridge.

Covers:

  * ``register_subscribers`` subscribes ``_on_event`` against every
    event in :data:`core.events.event_catalog.ALL_EVENTS`.
  * The universal handler only matches workflows whose
    ``enabled_event_types`` includes the published event_type +
    whose ``org_id`` matches the envelope.
  * The matcher hits ONLY ``active`` workflows — draft / paused /
    archived are skipped.
  * Different orgs publishing the same event don't cross-fire.
  * Workflows without a ``contact_id`` in the envelope (e.g.
    ``time.daily_tick``) start runs with ``contact_id=NULL``.
  * Idempotency: replaying the same envelope (same ``event_id``)
    does NOT create a duplicate run.
  * ``update_enabled_event_types_from_graph`` re-derives the
    denormalised column from the persisted graph.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import (
    ALL_EVENTS,
    LEAD_CREATED,
    is_known_event,
)
from src.app.core.workflows import (
    service as workflows_service,
    trigger_handlers,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowRun,
    WorkflowStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


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


async def _seed_workflow(
    test_db,
    *,
    org_id,
    event_type: str = LEAD_CREATED,
    status: WorkflowStatus = WorkflowStatus.active,
    re_enroll: WorkflowReEnrollmentRule = WorkflowReEnrollmentRule.never,
) -> Workflow:
    wf = Workflow(
        org_id=org_id,
        name=f"WF-{uuid.uuid4().hex[:6]}",
        status=status,
        current_version=1,
        graph={
            "nodes": [
                {
                    "id": "t1",
                    "type": "trigger.lead_created",
                    "config": {"event_type": event_type},
                },
                {"id": "end", "type": "flow.end", "config": {}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "end"}],
        },
        enabled_event_types=[event_type],
        re_enrollment_rule=re_enroll,
    )
    test_db.add(wf)
    await test_db.commit()
    await test_db.refresh(wf)
    return wf


# ---------------------------------------------------------------------------
# Catalog registration
# ---------------------------------------------------------------------------


def test_catalog_is_known_event_for_documented_types():
    """Sanity-check the catalog helper — every constant in
    ALL_EVENTS resolves through ``is_known_event``."""
    for event in ALL_EVENTS:
        assert is_known_event(event), f"catalog miss for {event}"


def test_register_subscribers_subscribes_universal_handler():
    """Re-running ``register_subscribers`` is idempotent — the
    bus's per-handler dedupe keeps the registry from doubling up."""
    # Sweep + re-register to assert the resulting subscriber state.
    trigger_handlers.unregister_subscribers()
    trigger_handlers.register_subscribers()
    trigger_handlers.register_subscribers()  # idempotent

    # Pick a sentinel event from the catalog + verify the handler
    # is present exactly once.
    bucket = events_bus._subscribers.get(LEAD_CREATED, [])  # noqa: SLF001
    matches = [h for h in bucket if h is trigger_handlers._on_event]
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# Universal handler matching
# ---------------------------------------------------------------------------


async def test_on_event_starts_run_for_active_workflow(test_db, org_id):
    wf = await _seed_workflow(test_db, org_id=org_id)
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name) "
            "VALUES (:id, :org_id, :name)"
        ),
        {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
    )
    await test_db.commit()

    envelope = {
        "event_type": LEAD_CREATED,
        "org_id": org_id,
        "event_id": "lead_created:abc",
        "contact_id": str(contact_id),
        "lead_id": str(uuid.uuid4()),
    }

    # Mock the Celery scheduler so no real workers fire — the
    # engine still inserts the run row + the step_run for the
    # trigger node.
    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(envelope)

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].contact_id == contact_id
    assert rows[0].trigger_event_id == "lead_created:abc"


async def test_on_event_skips_draft_and_paused_workflows(test_db, org_id):
    """Only ``status='active'`` workflows trigger runs."""
    await _seed_workflow(
        test_db, org_id=org_id, status=WorkflowStatus.draft
    )
    await _seed_workflow(
        test_db, org_id=org_id, status=WorkflowStatus.paused
    )

    envelope = {
        "event_type": LEAD_CREATED,
        "org_id": org_id,
        "event_id": "x",
        "contact_id": None,
    }
    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(envelope)

    rows = (await test_db.execute(select(WorkflowRun))).scalars().all()
    assert rows == []


async def test_on_event_isolates_orgs(test_db, org_id):
    """An event for org A doesn't fire workflows in org B."""
    other_org = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {
            "id": str(other_org),
            "name": "Other",
            "slug": f"other-{other_org.hex[:6]}",
        },
    )
    await test_db.commit()

    wf_a = await _seed_workflow(test_db, org_id=org_id)
    wf_b = await _seed_workflow(test_db, org_id=other_org)

    envelope = {
        "event_type": LEAD_CREATED,
        "org_id": org_id,
        "event_id": "x",
        "contact_id": None,
    }
    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(envelope)

    rows_a = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf_a.id)
        )
    ).scalars().all()
    rows_b = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf_b.id)
        )
    ).scalars().all()
    assert len(rows_a) == 1
    assert rows_b == []


async def test_on_event_without_contact_starts_null_contact_run(
    test_db, org_id
):
    """``time.daily_tick`` + similar events publish without a
    contact — the run is created with ``contact_id=NULL``."""
    wf = await _seed_workflow(
        test_db, org_id=org_id, event_type="time.daily_tick"
    )
    envelope = {
        "event_type": "time.daily_tick",
        "org_id": org_id,
        "event_id": "tick:2026-06-29",
        # No contact_id key at all.
    }

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(envelope)

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].contact_id is None


async def test_on_event_idempotent_on_trigger_event_id(test_db, org_id):
    """Replaying the same envelope (same ``event_id``) does NOT
    create a duplicate run."""
    wf = await _seed_workflow(test_db, org_id=org_id)
    contact_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name) "
            "VALUES (:id, :org_id, :name)"
        ),
        {"id": str(contact_id), "org_id": str(org_id), "name": "Asha"},
    )
    await test_db.commit()

    envelope = {
        "event_type": LEAD_CREATED,
        "org_id": org_id,
        "event_id": "deterministic-key",
        "contact_id": str(contact_id),
    }

    from src.app.core.workflows import engine as workflows_engine

    with patch.object(workflows_engine, "_schedule_process_step"):
        await trigger_handlers._on_event(envelope)
        await trigger_handlers._on_event(envelope)

    rows = (
        await test_db.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
        )
    ).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# update_enabled_event_types_from_graph
# ---------------------------------------------------------------------------


async def test_update_enabled_event_types_rewrites_column(test_db, org_id):
    """Patching the graph rewrites ``enabled_event_types`` so the
    matcher's array filter stays in sync."""
    wf = await _seed_workflow(test_db, org_id=org_id, event_type=LEAD_CREATED)
    # Manually rewrite the graph to switch the trigger event.
    wf.graph = {
        "nodes": [
            {
                "id": "t1",
                "type": "trigger.quote_sent",
                "position": {"x": 0, "y": 0},
                "config": {"event_type": "quote.sent"},
            },
            {
                "id": "end",
                "type": "flow.end",
                "position": {"x": 100, "y": 0},
                "config": {},
            },
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "end"}],
    }
    # Leave the denormalised column stale on purpose — the helper
    # should re-derive it.
    wf.enabled_event_types = ["lead.created"]
    await test_db.commit()

    token = set_context(RequestContext(org_id=org_id))
    try:
        new_types = (
            await workflows_service.update_enabled_event_types_from_graph(
                test_db, org_id=org_id, workflow_id=wf.id
            )
        )
    finally:
        reset_context(token)

    assert new_types == ["quote.sent"]
    await test_db.refresh(wf)
    assert wf.enabled_event_types == ["quote.sent"]
