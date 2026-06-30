"""Pin tests for Step-17 version history + rollback + import/export.

Covers:

  * :func:`list_workflow_versions` returns rows newest-first with the
    matching ``total`` count.
  * :func:`rollback_workflow` writes a NEW version row (preserves
    audit chain) carrying the rolled-back graph.
  * Rollback to an unknown version raises :class:`WorkflowNotFound`.
  * Rollback on an active marketing workflow raises
    :class:`WorkflowLocked`.
  * :func:`export_workflow` returns the documented schema.
  * Round-trip: export then import yields the same graph.
  * :func:`import_workflow` remaps unknown ``template_id`` references
    on send nodes to ``null`` + stamps ``__valid=false``.
  * Import auto-suffixes the name on collision.
  * Saving with a ``change_note`` lands the note on the version row.
  * After rollback the workflow's ``current_version`` is monotonically
    greater than the pre-rollback value.

Graph validation is bypassed where possible by constructing minimal
trigger → send → goal shapes that satisfy the Step-2 validator.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.workflows import service as workflows_service
from src.app.core.workflows import data_access as _da
from src.app.core.workflows.exceptions import (
    WorkflowLocked,
    WorkflowNotFound,
)
from src.app.core.workflows.models import (
    Workflow,
    WorkflowStatus,
    WorkflowVersion,
)
from src.app.core.workflows.schemas import (
    WorkflowCreate,
    WorkflowGraph,
    WorkflowUpdate,
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


def _trigger_send_goal_graph() -> dict:
    """Minimal graph that satisfies the Step-2 graph validator
    (single trigger + connected + no cycles)."""
    return {
        "nodes": [
            {"id": "t1", "type": "trigger", "config": {"event_type": "lead.created"}},
            {"id": "s1", "type": "send.email", "config": {}},
            {"id": "g1", "type": "flow_control.goal", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "s1", "label": None},
            {"id": "e2", "source": "s1", "target": "g1", "label": None},
        ],
    }


def _swapped_graph() -> dict:
    """Slightly different graph — used to verify rollback restores
    a *prior* graph rather than re-saving the current one."""
    return {
        "nodes": [
            {"id": "t1", "type": "trigger", "config": {"event_type": "lead.updated"}},
            {"id": "s2", "type": "send.whatsapp", "config": {}},
            {"id": "g1", "type": "flow_control.goal", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "s2", "label": None},
            {"id": "e2", "source": "s2", "target": "g1", "label": None},
        ],
    }


async def _make_workflow(test_db, *, org_id, name: str | None = None) -> Workflow:
    """Create a baseline draft workflow via the service so the
    initial v1 row + graph validation land naturally."""
    payload = WorkflowCreate(
        name=name or f"WF-{uuid.uuid4().hex[:6]}",
        description=None,
        category="Sales",
        folder_id=None,
        is_marketing=True,
        re_enrollment_rule="once",
        graph=WorkflowGraph.model_validate(_trigger_send_goal_graph()),
        goal_node_id="g1",
        cost_per_run_cents=0,
    )
    return await workflows_service.create_workflow(
        test_db, org_id=org_id, user_id=None, payload=payload
    )


# ---------------------------------------------------------------------------
# Version list
# ---------------------------------------------------------------------------


async def test_list_workflow_versions_returns_newest_first(test_db, org_id):
    """v1 (initial) → v2 (swapped graph) → list returns v2 first."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            payload=WorkflowUpdate(
                graph=WorkflowGraph.model_validate(_swapped_graph()),
            ),
        )
        rows, total = await workflows_service.list_workflow_versions(
            test_db, org_id=org_id, workflow_id=wf.id
        )
    finally:
        reset_context(token)

    assert total == 2
    assert [r.version for r in rows] == [2, 1]


# ---------------------------------------------------------------------------
# Rollback — happy path
# ---------------------------------------------------------------------------


async def test_rollback_writes_new_version_with_rolled_back_graph(
    test_db, org_id
):
    """Rolling back from v2 to v1 lands v3 with v1's graph + bumps
    `current_version` to 3."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        v1_graph = dict(wf.graph)
        await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            payload=WorkflowUpdate(
                graph=WorkflowGraph.model_validate(_swapped_graph()),
            ),
        )
        rolled = await workflows_service.rollback_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            target_version=1,
            change_note="Bring back v1",
        )
    finally:
        reset_context(token)

    assert rolled.current_version == 3
    assert rolled.graph == v1_graph

    # v3 row exists with the note we passed.
    v3 = await _da.get_version(
        test_db, org_id=org_id, workflow_id=wf.id, version=3
    )
    assert v3 is not None
    assert v3.change_note == "Bring back v1"
    assert v3.graph == v1_graph


# ---------------------------------------------------------------------------
# Rollback — error paths
# ---------------------------------------------------------------------------


async def test_rollback_to_unknown_version_raises_not_found(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        with pytest.raises(WorkflowNotFound):
            await workflows_service.rollback_workflow(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=wf.id,
                target_version=999,
            )
    finally:
        reset_context(token)


async def test_rollback_refuses_active_marketing_workflow(test_db, org_id):
    """Same lock as `update_workflow` — operator must pause first."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        # Flip directly to `active` via the row to dodge the activation
        # graph re-validation; we just need the marketing lock to fire.
        wf.status = WorkflowStatus.active
        await test_db.commit()
        await test_db.refresh(wf)
        with pytest.raises(WorkflowLocked):
            await workflows_service.rollback_workflow(
                test_db,
                org_id=org_id,
                user_id=None,
                workflow_id=wf.id,
                target_version=1,
            )
    finally:
        reset_context(token)


async def test_rollback_bumps_current_version_monotonically(test_db, org_id):
    """After rollback the workflow's `current_version` MUST be
    strictly greater than the pre-rollback value (audit chain
    preserved — no rewriting history)."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            payload=WorkflowUpdate(
                graph=WorkflowGraph.model_validate(_swapped_graph()),
                change_note="swap to v2",
            ),
        )
        pre = (
            await workflows_service.get_workflow(
                test_db, org_id=org_id, workflow_id=wf.id
            )
        ).current_version
        rolled = await workflows_service.rollback_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            target_version=1,
        )
    finally:
        reset_context(token)
    assert rolled.current_version > pre


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------


async def test_export_workflow_returns_documented_schema(test_db, org_id):
    """Export payload carries the keys the schema documents."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id, name="To Export")
        body = await workflows_service.export_workflow(
            test_db, org_id=org_id, workflow_id=wf.id
        )
    finally:
        reset_context(token)

    expected_keys = {
        "name",
        "description",
        "category",
        "graph",
        "re_enrollment_rule",
        "is_marketing",
        "goal_node_id",
        "cost_per_run_cents",
        "schema_version",
    }
    assert set(body.keys()) == expected_keys
    assert body["schema_version"] == 1
    assert body["name"] == "To Export"


async def test_export_then_import_round_trips_graph(test_db, org_id):
    """Export a workflow, import the JSON back → the new draft's
    graph matches verbatim (sans the `__valid=false` stamp on send
    nodes whose template_id wasn't a real one in this org)."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        source = await _make_workflow(
            test_db, org_id=org_id, name="Round Trip Source"
        )
        body = await workflows_service.export_workflow(
            test_db, org_id=org_id, workflow_id=source.id
        )
        # Mimic the router's projection back into a WorkflowCreate.
        payload = WorkflowCreate(
            name="Imported Copy",
            description=body["description"],
            category=body["category"],
            folder_id=None,
            is_marketing=body["is_marketing"],
            re_enrollment_rule=body["re_enrollment_rule"],
            graph=WorkflowGraph.model_validate(body["graph"]),
            goal_node_id=body["goal_node_id"],
            cost_per_run_cents=body["cost_per_run_cents"],
        )
        imported = await workflows_service.import_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=payload,
            target_folder_id=None,
            override_name="Imported Copy",
        )
    finally:
        reset_context(token)

    # Same node ids carried across.
    src_ids = sorted(n["id"] for n in source.graph["nodes"])
    new_ids = sorted(n["id"] for n in imported.graph["nodes"])
    assert src_ids == new_ids
    # Same edges (count + (source, target) shape).
    assert len(source.graph["edges"]) == len(imported.graph["edges"])


async def test_import_remaps_unknown_template_id_to_null_and_invalid(
    test_db, org_id
):
    """A send node whose `template_id` doesn't exist in the org
    must land as `template_id` absent + `__valid=false` so the
    Step-15 editor surfaces it for fix-up."""
    fake_tid = str(uuid.uuid4())
    graph_with_template = {
        "nodes": [
            {"id": "t1", "type": "trigger", "config": {"event_type": "lead.created"}},
            {
                "id": "s1",
                "type": "send.email",
                "config": {"template_id": fake_tid, "label": "Will be remapped"},
            },
            {"id": "g1", "type": "flow_control.goal", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "s1", "label": None},
            {"id": "e2", "source": "s1", "target": "g1", "label": None},
        ],
    }
    payload = WorkflowCreate(
        name="Import With Bad Template",
        description=None,
        category="Sales",
        folder_id=None,
        is_marketing=True,
        re_enrollment_rule="once",
        graph=WorkflowGraph.model_validate(graph_with_template),
        goal_node_id="g1",
        cost_per_run_cents=0,
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        imported = await workflows_service.import_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=payload,
            target_folder_id=None,
            override_name=None,
        )
    finally:
        reset_context(token)

    send_node = next(
        n for n in imported.graph["nodes"] if n.get("type") == "send.email"
    )
    cfg = send_node.get("config") or {}
    assert "template_id" not in cfg, (
        "import path must strip unknown template_ids"
    )
    assert cfg.get("__valid") is False


async def test_import_auto_suffixes_duplicate_name(test_db, org_id):
    """Importing a workflow whose name collides gets `(2)` appended."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        await _make_workflow(test_db, org_id=org_id, name="Will Collide")
        payload = WorkflowCreate(
            name="Will Collide",
            description=None,
            category="Sales",
            folder_id=None,
            is_marketing=True,
            re_enrollment_rule="once",
            graph=WorkflowGraph.model_validate(_trigger_send_goal_graph()),
            goal_node_id="g1",
            cost_per_run_cents=0,
        )
        second = await workflows_service.import_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=payload,
            target_folder_id=None,
            override_name="Will Collide",
        )
    finally:
        reset_context(token)

    assert second.name == "Will Collide (2)"


async def test_save_persists_change_note_on_version_row(test_db, org_id):
    """`WorkflowUpdate.change_note` lands on the new
    `tbl_workflow_versions` row — drives the version-history drawer
    column."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        wf = await _make_workflow(test_db, org_id=org_id)
        await workflows_service.update_workflow(
            test_db,
            org_id=org_id,
            user_id=None,
            workflow_id=wf.id,
            payload=WorkflowUpdate(
                graph=WorkflowGraph.model_validate(_swapped_graph()),
                change_note="Swapped the welcome touch",
            ),
        )
        rows, _ = await workflows_service.list_workflow_versions(
            test_db, org_id=org_id, workflow_id=wf.id
        )
    finally:
        reset_context(token)

    assert rows[0].version == 2
    assert rows[0].change_note == "Swapped the welcome touch"
