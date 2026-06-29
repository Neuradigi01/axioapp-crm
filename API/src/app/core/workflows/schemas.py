"""Pydantic v2 schemas for the workflows module.

Three concept groups:

  * **Workflow CRUD** — ``WorkflowCreate`` / ``Update`` / ``Read``.
    The ``graph`` field carries a strictly-typed
    :class:`WorkflowGraph` so the router 422s on malformed shapes
    before the Step-2 validator's deeper semantic checks
    (no-cycle, single root, no orphan edges).
  * **Run reads** — :class:`WorkflowRunRead` /
    :class:`WorkflowStepRunRead` drive the Step-19 history UI.
  * **Folder CRUD** — :class:`WorkflowFolderCreate` /
    :class:`WorkflowFolderRead` drive the Step-13 list page's tree
    view.

The graph contract:

  * Each ``node`` is ``{id: str, type: str, position: {x, y},
    config: dict}``.
  * Each ``edge`` is ``{id: str, source: str, target: str,
    label?: str}``.
  * Every edge's ``source`` and ``target`` MUST reference a node in
    the same payload — the validator below enforces this so the
    Step-2 engine never has to defend against dangling edges.

Step 2 will layer in semantic rules (single trigger root, no cycles
in non-loop nodes, etc.); Step 1 only enforces the structural
contract.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.app.shared.schemas import ORMModel


# --- Graph shape ---------------------------------------------------------


class NodePosition(BaseModel):
    """Canvas coordinates for the React-flow-style renderer
    (Step 14 ships the canvas). Pure UI state; the engine ignores
    it. Stored on the graph for round-trip fidelity."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0


class GraphNode(BaseModel):
    """One node in the workflow graph. ``type`` is a free string
    (e.g. ``trigger.lead_created``, ``action.send.email``,
    ``branch.if``) — the engine's action registry decides what each
    type means at execution time."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=64)
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """One directed edge between two nodes. ``label`` carries the
    branch-output discriminator (``yes`` / ``no`` for if-nodes;
    arbitrary strings for switch-nodes)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    source: str = Field(..., min_length=1, max_length=64)
    target: str = Field(..., min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=64)


class WorkflowGraph(BaseModel):
    """The full ``{nodes, edges}`` payload stored on
    ``tbl_workflows.graph``. Validates that:

      * No duplicate node ids.
      * No duplicate edge ids.
      * Every edge's ``source`` + ``target`` references a node id
        present in this graph.

    Deeper semantic rules (single trigger root, no cycles) are
    Step 2's :mod:`core.workflows.service` validator — at Pydantic
    layer we just enforce the structural contract."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structural_checks(self) -> "WorkflowGraph":
        node_ids = {n.id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("workflow.graph contains duplicate node ids")

        edge_ids = {e.id for e in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("workflow.graph contains duplicate edge ids")

        for e in self.edges:
            if e.source not in node_ids:
                raise ValueError(
                    f"workflow.graph edge '{e.id}' references missing "
                    f"source node '{e.source}'"
                )
            if e.target not in node_ids:
                raise ValueError(
                    f"workflow.graph edge '{e.id}' references missing "
                    f"target node '{e.target}'"
                )
        return self


# --- Workflow CRUD -------------------------------------------------------


_WorkflowStatusLiteral = Literal["draft", "active", "paused", "archived"]
_ReEnrollmentLiteral = Literal["once", "daily", "never"]


class WorkflowCreate(BaseModel):
    """POST body for ``/api/v1/workflows`` (Step 3)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(default="Custom", max_length=64)
    folder_id: uuid.UUID | None = None
    is_marketing: bool = True
    re_enrollment_rule: _ReEnrollmentLiteral = "once"
    graph: WorkflowGraph = Field(default_factory=WorkflowGraph)
    goal_node_id: str | None = Field(default=None, max_length=64)
    cost_per_run_cents: int = Field(default=0, ge=0)


class WorkflowUpdate(BaseModel):
    """PATCH body — every field optional; unset keys retain the
    workflow's prior value. The Step-2 service decides whether the
    update produces a new version row in ``tbl_workflow_versions``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    folder_id: uuid.UUID | None = None
    status: _WorkflowStatusLiteral | None = None
    is_marketing: bool | None = None
    re_enrollment_rule: _ReEnrollmentLiteral | None = None
    graph: WorkflowGraph | None = None
    goal_node_id: str | None = Field(default=None, max_length=64)
    cost_per_run_cents: int | None = Field(default=None, ge=0)


class WorkflowRead(ORMModel):
    """Response shape for ``GET /api/v1/workflows/{id}``."""

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    category: str
    folder_id: uuid.UUID | None
    status: _WorkflowStatusLiteral
    current_version: int
    re_enrollment_rule: _ReEnrollmentLiteral
    is_marketing: bool
    graph: dict[str, Any]
    goal_node_id: str | None
    cost_per_run_cents: int
    enabled_event_types: list[str]
    ab_sibling_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @field_validator("status", "re_enrollment_rule", mode="before")
    @classmethod
    def _coerce_enum(cls, value: Any) -> Any:
        """Pull the ``.value`` off SQLAlchemy enum-bound instances
        before the Literal type narrows. Mirrors the pattern used
        elsewhere in core/ for status reads."""
        if value is None:
            return value
        return getattr(value, "value", value)


# --- Run history reads ---------------------------------------------------


class WorkflowStepRunRead(ORMModel):
    """One row in the Step-19 run-history table."""

    id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    step_index: int
    status: Literal["pending", "running", "completed", "skipped", "errored"]
    started_at: datetime
    completed_at: datetime | None
    output_edge_label: str | None
    skip_reason: str | None
    payload: dict[str, Any]
    error: str | None

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_enum(cls, value: Any) -> Any:
        if value is None:
            return value
        return getattr(value, "value", value)


class WorkflowRunRead(ORMModel):
    """One enrolment's summary row for the Step-19 list."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    version: int
    contact_id: uuid.UUID | None
    trigger_event_id: str | None
    status: Literal[
        "pending", "running", "completed", "paused", "canceled", "errored"
    ]
    current_node_id: str | None
    outcome: Literal[
        "goal_reached", "completed", "canceled", "errored"
    ] | None
    error: str | None
    started_at: datetime
    next_step_at: datetime | None
    completed_at: datetime | None

    @field_validator("status", "outcome", mode="before")
    @classmethod
    def _coerce_enum(cls, value: Any) -> Any:
        if value is None:
            return value
        return getattr(value, "value", value)


# --- Folder CRUD ---------------------------------------------------------


class WorkflowFolderCreate(BaseModel):
    """POST body for ``/api/v1/workflows/folders`` (Step 3)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    parent_folder_id: uuid.UUID | None = None
    display_order: int = Field(default=0, ge=0)


class WorkflowFolderRead(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    parent_folder_id: uuid.UUID | None
    display_order: int
    created_at: datetime
    updated_at: datetime


class EventWaitRead(ORMModel):
    """Step-11 read shape for the ``tbl_workflow_event_waits`` table.
    Drives the per-run wait-status view on Step-19's diagnostics
    surface."""

    id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    event_type: str
    contact_id: uuid.UUID | None
    expires_at: datetime
    created_at: datetime


__all__ = [
    "EventWaitRead",
    "GraphEdge",
    "GraphNode",
    "NodePosition",
    "WorkflowCreate",
    "WorkflowFolderCreate",
    "WorkflowFolderRead",
    "WorkflowGraph",
    "WorkflowRead",
    "WorkflowRunRead",
    "WorkflowStepRunRead",
    "WorkflowUpdate",
]
