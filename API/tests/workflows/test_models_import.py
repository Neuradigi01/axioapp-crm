"""Pin tests for the Step-1 workflows foundation.

Covers:

  * All five models import cleanly + inherit ``TenantScoped``.
  * All five tables register with ``Base.metadata`` (so Alembic
    autogenerate picks them up + the test-DB fixture creates
    them).
  * Status / outcome / re_enrollment enums carry the documented
    values verbatim.
  * Pydantic ``WorkflowCreate`` round-trips with an empty graph.
  * ``WorkflowGraph`` rejects nodes without an ``id`` / ``type``.
  * ``WorkflowGraph`` rejects edges referencing missing node ids.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.workflows.models import (
    Workflow,
    WorkflowFolder,
    WorkflowReEnrollmentRule,
    WorkflowRun,
    WorkflowRunOutcome,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepRunStatus,
    WorkflowVersion,
)
from src.app.core.workflows.schemas import WorkflowCreate, WorkflowGraph
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


def test_all_five_models_inherit_tenant_scoped():
    """Every workflows table is tenant-scoped — RLS + auto-org_id
    filter MUST apply."""
    for model in (
        Workflow,
        WorkflowFolder,
        WorkflowVersion,
        WorkflowRun,
        WorkflowStepRun,
    ):
        assert issubclass(model, TenantScoped), (
            f"{model.__name__} must inherit TenantScoped (RLS gate)"
        )


def test_all_five_tables_registered_with_base_metadata():
    """Models must be discoverable via ``Base.metadata.tables`` so
    Alembic autogenerate + the test-DB fixture pick them up."""
    expected = {
        "tbl_workflows",
        "tbl_workflow_folders",
        "tbl_workflow_versions",
        "tbl_workflow_runs",
        "tbl_workflow_step_runs",
    }
    registered = set(Base.metadata.tables.keys())
    assert expected.issubset(registered), f"missing tables: {expected - registered}"


def test_workflow_status_enum_values():
    assert {m.value for m in WorkflowStatus} == {
        "draft",
        "active",
        "paused",
        "archived",
    }


def test_workflow_run_status_enum_values():
    assert {m.value for m in WorkflowRunStatus} == {
        "pending",
        "running",
        "completed",
        "paused",
        "canceled",
        "errored",
    }


def test_workflow_run_outcome_enum_values():
    assert {m.value for m in WorkflowRunOutcome} == {
        "goal_reached",
        "completed",
        "canceled",
        "errored",
    }


def test_workflow_step_run_status_enum_values():
    assert {m.value for m in WorkflowStepRunStatus} == {
        "pending",
        "running",
        "completed",
        "skipped",
        "errored",
    }


def test_re_enrollment_rule_enum_values():
    assert {m.value for m in WorkflowReEnrollmentRule} == {
        "once",
        "daily",
        "never",
    }


def test_workflow_create_round_trips_empty_graph():
    payload = WorkflowCreate(
        name="Welcome flow",
        graph=WorkflowGraph(nodes=[], edges=[]),
    )
    assert payload.name == "Welcome flow"
    assert payload.graph.nodes == []
    assert payload.graph.edges == []
    # Defaults applied for unset fields.
    assert payload.re_enrollment_rule == "once"
    assert payload.is_marketing is True
    assert payload.cost_per_run_cents == 0


def test_workflow_graph_rejects_node_without_id():
    with pytest.raises(ValidationError):
        WorkflowGraph(nodes=[{"type": "trigger.lead_created"}], edges=[])


def test_workflow_graph_rejects_node_without_type():
    with pytest.raises(ValidationError):
        WorkflowGraph(nodes=[{"id": "n1"}], edges=[])


def test_workflow_graph_rejects_edge_with_missing_source():
    with pytest.raises(ValidationError):
        WorkflowGraph(
            nodes=[{"id": "n1", "type": "trigger.lead_created"}],
            edges=[{"id": "e1", "source": "missing", "target": "n1"}],
        )


def test_workflow_graph_rejects_edge_with_missing_target():
    with pytest.raises(ValidationError):
        WorkflowGraph(
            nodes=[{"id": "n1", "type": "trigger.lead_created"}],
            edges=[{"id": "e1", "source": "n1", "target": "missing"}],
        )


def test_workflow_graph_rejects_duplicate_node_ids():
    with pytest.raises(ValidationError):
        WorkflowGraph(
            nodes=[
                {"id": "n1", "type": "trigger.lead_created"},
                {"id": "n1", "type": "action.send.email"},
            ],
            edges=[],
        )
