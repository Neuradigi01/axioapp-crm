"""Pin tests for Step-20 email_sequences → workflows absorption.

Covers:

  * ``scheduler.tick`` is a no-op (returns 0).
  * The Celery task wrapper returns the deprecated sentinel.
  * The sequence → workflow translator builds the expected graph
    shape (trigger + wait + send per step + goal).
  * ``email_sequences.service.enroll`` shims through
    ``workflows.engine.start_run`` when a matching workflow row is
    present.
  * The shim's matching is name-based: ``f"Sequence: {seq.name}"``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.email_sequences import scheduler as es_scheduler
from src.app.core.email_sequences import service as es_service
from src.app.core.email_sequences.tasks import tick_email_sequences
from src.app.core.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStatus,
)
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Scheduler no-op
# ---------------------------------------------------------------------------


async def test_scheduler_tick_is_noop():
    """Step 20 absorbed sequence runtime into workflows — tick returns
    0 to keep historical log parsers / observability working."""
    assert await es_scheduler.tick() == 0


def test_celery_wrapper_returns_deprecated_sentinel():
    """The beat task entry stays registered for one release; the
    response carries ``deprecated=True`` so dashboards flag it."""
    result = tick_email_sequences()
    assert result == {"processed": 0, "deprecated": True}


# ---------------------------------------------------------------------------
# Translator (data migration helper)
# ---------------------------------------------------------------------------


def test_sequence_translator_builds_linear_graph():
    """The 0145 migration's translator wraps each step in
    ``wait → send.email`` + caps with a goal node."""
    # Import the helper directly from the migration module so the
    # test pins the exact translation logic.
    import importlib

    mod = importlib.import_module(
        "alembic.versions.0145_migrate_sequences_to_workflows"
    )
    graph, goal_id = mod._build_graph_for_sequence(
        sequence_name="Welcome series",
        steps=[
            {"step_order": 1, "delay_days": 0, "template_id": uuid.uuid4()},
            {"step_order": 2, "delay_days": 3, "template_id": uuid.uuid4()},
            {"step_order": 3, "delay_days": 7, "template_id": uuid.uuid4()},
        ],
    )
    node_types = [n["type"] for n in graph["nodes"]]
    # Expect: trigger.manual + (send) + (wait + send) + (wait + send) + goal.
    assert node_types[0] == "trigger.manual"
    assert node_types[-1] == "flow_control.goal"
    assert node_types.count("send.email") == 3
    assert node_types.count("flow_control.wait") == 2  # steps with delay>0
    assert any(n["id"] == goal_id for n in graph["nodes"])


def test_sequence_translator_step_without_delay_skips_wait():
    """A step with ``delay_days=0`` should NOT emit a wait node — the
    send fires immediately after the previous send / trigger."""
    import importlib

    mod = importlib.import_module(
        "alembic.versions.0145_migrate_sequences_to_workflows"
    )
    graph, _ = mod._build_graph_for_sequence(
        sequence_name="Instant",
        steps=[{"step_order": 1, "delay_days": 0, "template_id": None}],
    )
    node_types = [n["type"] for n in graph["nodes"]]
    assert "flow_control.wait" not in node_types
    assert node_types.count("send.email") == 1


# ---------------------------------------------------------------------------
# Service shim
# ---------------------------------------------------------------------------


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
            "name": "AbsorbDemo",
            "slug": f"abs-{org_id.hex[:6]}",
        },
    )
    await test_db.commit()
    return org_id


@pytest_asyncio.fixture
async def contact_id(test_db, org_id):
    cid = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_contacts (id, org_id, full_name) "
            "VALUES (:id, :org, :name)"
        ),
        {"id": str(cid), "org": str(org_id), "name": "Asha"},
    )
    await test_db.commit()
    return cid


async def test_try_enroll_via_workflow_returns_none_when_no_match(
    test_db, org_id, contact_id
):
    """If no matching workflow row exists for the sequence name, the
    shim returns None so the legacy code path can run."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        result = await es_service._try_enroll_via_workflow(
            test_db,
            org_id=org_id,
            sequence_name="No-such-sequence",
            contact_ids=[contact_id],
        )
    finally:
        reset_context(token)
    assert result is None


async def test_try_enroll_via_workflow_starts_run_when_matched(
    test_db, org_id, contact_id
):
    """When a workflow named ``Sequence: <name>`` exists for the org,
    the shim calls ``workflows.engine.start_run`` + returns a
    populated result row per contact."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        # Insert a workflow with a trigger node so start_run succeeds.
        wf = Workflow(
            org_id=org_id,
            name="Sequence: Welcome series",
            status=WorkflowStatus.active,
            current_version=1,
            graph={
                "nodes": [
                    {
                        "id": "trig",
                        "type": "trigger.manual",
                        "config": {"event_type": "sequence.manual_enroll"},
                    },
                    {"id": "goal", "type": "flow_control.goal", "config": {}},
                ],
                "edges": [{"id": "e1", "source": "trig", "target": "goal"}],
            },
            goal_node_id="goal",
            enabled_event_types=["sequence.manual_enroll"],
        )
        test_db.add(wf)
        await test_db.commit()
        await test_db.refresh(wf)

        results = await es_service._try_enroll_via_workflow(
            test_db,
            org_id=org_id,
            sequence_name="Welcome series",
            contact_ids=[contact_id],
        )
        await test_db.commit()

        runs = list(
            (
                await test_db.execute(
                    select(WorkflowRun).where(WorkflowRun.workflow_id == wf.id)
                )
            ).scalars()
        )
    finally:
        reset_context(token)

    assert results is not None
    assert len(results) == 1
    assert results[0].enrolled is True
    assert results[0].contact_id == contact_id
    assert results[0].enrollment_id is not None
    assert len(runs) == 1
    assert runs[0].contact_id == contact_id
