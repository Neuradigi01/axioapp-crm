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
    def _structural_checks(self) -> WorkflowGraph:
        node_ids = {n.id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("workflow.graph contains duplicate node ids")

        edge_ids = {e.id for e in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("workflow.graph contains duplicate edge ids")

        for e in self.edges:
            if e.source not in node_ids:
                raise ValueError(
                    f"workflow.graph edge '{e.id}' references missing source node '{e.source}'"
                )
            if e.target not in node_ids:
                raise ValueError(
                    f"workflow.graph edge '{e.id}' references missing target node '{e.target}'"
                )
        return self


# --- Workflow CRUD -------------------------------------------------------


_WorkflowStatusLiteral = Literal["draft", "active", "paused", "archived"]
_ReEnrollmentLiteral = Literal["once", "daily", "never"]
_ABWinnerMetricLiteral = Literal["goal_conversion", "reply_rate", "open_rate", "custom"]


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
    # Step 17 — operator-supplied description of the change, lands on
    # the new ``tbl_workflow_versions`` row + drives the version-
    # history drawer's column.
    change_note: str | None = Field(default=None, max_length=240)


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
    # Step 18 — A/B-test columns; surfaced so the canvas banner +
    # comparison page can render without a second round-trip.
    ab_paired_workflow_id: uuid.UUID | None = None
    ab_test_started_at: datetime | None = None
    ab_test_holdback_until: datetime | None = None
    ab_test_winner_metric: _ABWinnerMetricLiteral | None = None
    ab_test_min_runs_per_variant: int | None = None
    ab_test_winner_workflow_id: uuid.UUID | None = None
    ab_test_decided_at: datetime | None = None
    # Step 19 — list-page mini-stats refreshed every 5 min by
    # ``tasks.refresh_workflow_cached_counters``.
    cached_running_count: int = 0
    cached_completed_today_count: int = 0
    # Step 21 — system-default flag (drives "System" badge + delete
    # protection in the list page).
    is_system_default: bool = False
    created_at: datetime
    updated_at: datetime
    # ``tasks/workflow-scheduling`` Step 5 — populated by the list
    # endpoint via a schedule-summary aggregate join. NULL / 0 for
    # the single-workflow GET (kept optional so single-row callers
    # don't have to compute the summary they won't render).
    active_schedule_count: int = 0
    next_scheduled_at: datetime | None = None

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
    status: Literal["pending", "running", "completed", "paused", "canceled", "errored"]
    current_node_id: str | None
    outcome: Literal["goal_reached", "completed", "canceled", "errored"] | None
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


# --- Step 17: version history + rollback + import/export ---------------


class WorkflowVersionSummaryRead(ORMModel):
    """Row in the version-history drawer's list. The full graph is
    fetched separately via :class:`WorkflowVersionDetailRead` when the
    operator clicks "View" — keeps the drawer scroll cheap."""

    id: uuid.UUID
    version: int
    change_note: str | None = None
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime


class WorkflowVersionListResponse(BaseModel):
    items: list[WorkflowVersionSummaryRead]
    total: int


class WorkflowVersionDetailRead(WorkflowVersionSummaryRead):
    """Full graph for one historical version — drives the "View"
    overlay in the canvas page."""

    workflow_id: uuid.UUID
    graph: dict


class RollbackRequest(BaseModel):
    """`POST /workflows/{id}/rollback` body."""

    model_config = ConfigDict(extra="forbid")

    target_version: int = Field(..., ge=1)
    change_note: str | None = Field(default=None, max_length=240)


class WorkflowExport(BaseModel):
    """Schema for the portable JSON export. Internal UUIDs (template
    references, contact ids) are kept verbatim — the importer
    remaps unknown references to ``null`` so the new draft surfaces
    the missing-template validation marker per the Step-15 editor.

    ``schema_version`` is 1 today. If we evolve the graph shape, the
    importer will need a per-version migration step before persisting.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=120)
    description: str | None = None
    category: str
    graph: WorkflowGraph
    re_enrollment_rule: str = "once"
    is_marketing: bool = True
    goal_node_id: str | None = None
    cost_per_run_cents: int = 0
    schema_version: int = Field(default=1, ge=1, le=1)


class WorkflowImportRequest(BaseModel):
    """`POST /workflows/import` body."""

    model_config = ConfigDict(extra="forbid")

    json_body: WorkflowExport = Field(..., alias="json")
    target_folder_id: uuid.UUID | None = Field(default=None)
    name: str | None = Field(default=None, max_length=120)


# --- Step 18: A/B testing ----------------------------------------------


class PairABRequest(BaseModel):
    """`POST /workflows/{id}/pair-ab` body — pair the named workflow
    with ``sibling_id`` as an A/B test. Both must be drafts with the
    same trigger event_type."""

    model_config = ConfigDict(extra="forbid")

    sibling_id: uuid.UUID
    holdback_seconds: int = Field(..., ge=3600, le=60 * 60 * 24 * 30)
    metric: _ABWinnerMetricLiteral = "goal_conversion"
    min_runs_per_variant: int = Field(default=50, ge=10, le=10_000)


class ABStatsResponse(BaseModel):
    """Live A/B stats — drives the canvas banner + comparison page."""

    workflow_id: uuid.UUID
    sibling_workflow_id: uuid.UUID
    a_workflow_id: uuid.UUID
    b_workflow_id: uuid.UUID
    a_total_runs: int
    a_goal_runs: int
    a_rate: float
    b_total_runs: int
    b_goal_runs: int
    b_rate: float
    p_value: float | None
    winner: Literal["a", "b", "inconclusive"]
    holdback_until: datetime | None
    decided_at: datetime | None
    min_runs_per_variant: int


# --- Step 19: analytics + diagnostics -----------------------------------


class WorkflowAnalyticsWindow(BaseModel):
    """The (since, until) window an analytics response covers."""

    since: datetime
    until: datetime


class WorkflowAnalyticsTotals(BaseModel):
    """Headline KPI block for the analytics dashboard."""

    enrolled: int
    completed: int
    goal_reached: int
    errored: int
    running: int
    conversion_rate: float
    avg_completion_seconds: float | None
    estimated_cost_cents: int


class WorkflowFunnelRow(BaseModel):
    """One node's slot in the per-step funnel."""

    node_id: str
    label: str
    node_type: str
    total: int
    completed_count: int
    skipped_count: int
    errored_count: int


class WorkflowSendMetricRow(BaseModel):
    """One channel's rollup row."""

    channel: str
    total: int
    delivered: int
    skipped: int
    errored: int
    delivery_rate: float


class WorkflowAnalyticsResponse(BaseModel):
    """Full analytics response — drives the Step-19 dashboard."""

    workflow_id: uuid.UUID
    window: WorkflowAnalyticsWindow
    totals: WorkflowAnalyticsTotals
    funnel: list[WorkflowFunnelRow]
    skip_reasons: dict[str, dict[str, int]]
    send_metrics: list[WorkflowSendMetricRow]


class WorkflowDailyRateRow(BaseModel):
    """One day's enrolled/completed/goal-reached counts."""

    date: str
    enrolled: int
    completed: int
    goal_reached: int


class WorkflowDailyRateResponse(BaseModel):
    items: list[WorkflowDailyRateRow]


class _DiagnosticsConditionTrace(BaseModel):
    """The per-leaf evaluation trace the diagnostics tool surfaces.

    Each entry mirrors one leaf node of the condition AST: the path
    that was resolved, the resolved value (post-coercion), and the
    True/False the evaluator returned. Compound nodes (``all`` /
    ``any`` / ``not``) carry their child traces inline."""

    op: str | None = None
    path: str | None = None
    resolved_value: Any | None = None
    value: Any | None = None
    result: bool
    missing: bool = False
    kind: Literal["leaf", "all", "any", "not", "empty", "invalid"] = "leaf"
    children: list[Any] | None = None
    error: str | None = None


class WorkflowDiagnosticsEntry(BaseModel):
    """One workflow's eligibility decision in the diagnostics
    response."""

    workflow_id: uuid.UUID
    workflow_name: str
    eligible: bool
    reason: str | None
    trigger_condition_trace: _DiagnosticsConditionTrace | None
    re_enrollment_decision: Literal["allowed", "blocked_once", "blocked_daily", "n/a"]
    resolved_context: dict[str, Any]


class WorkflowDiagnosticsResponse(BaseModel):
    """Top-level diagnostics response — every workflow in the org
    that subscribes to the event."""

    contact_id: uuid.UUID
    event_type: str
    synthesised_payload: bool
    entries: list[WorkflowDiagnosticsEntry]


# --- Schedule schemas (workflow-scheduling Step 3) -----------------------
#
# Three request shapes + one response, plus a preview surface.
#
# Mass-assignment shield: every Create/Update carries
# ``ConfigDict(extra="forbid")`` so server-owned fields
# (``runs_completed``, ``next_run_at``, ``last_run_at``,
# ``consecutive_empty_fires``, ``deactivation_reason``,
# ``org_id``, ``created_by_user_id``, ``created_at``,
# ``updated_at``) get a 422 the moment a client tries to set them.
# ``active`` is intentionally NOT declared on ``ScheduleUpdate`` so
# operators go through ``POST /pause`` or ``POST /resume`` (dedicated
# audit-friendly endpoints) rather than flipping it via PATCH.
#
# ``config_json`` is a free-form dict at the schema layer — the
# service-layer ``_validate_config_and_bounds`` runs kind-specific
# validation (cron / interval / weekly / etc.) and raises
# ``ScheduleValidationError`` on rejection. The router maps that to
# 422 with a friendly reason.


_SCHEDULE_KIND_LITERAL = Literal["once", "daily", "weekly", "monthly", "interval", "cron"]
_ON_MISSED_LITERAL = Literal["skip", "run_once", "backfill_all"]
_CONCURRENCY_LITERAL = Literal["allow", "forbid", "replace"]


class ScheduleCreate(BaseModel):
    """POST /workflows/{workflow_id}/schedules body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    schedule_kind: _SCHEDULE_KIND_LITERAL
    config_json: dict[str, Any] = Field(default_factory=dict)
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "IANA tz string. When omitted, defaults to the org's timezone (or UTC if that's unset)."
        ),
    )
    starts_at: datetime
    end_at: datetime | None = None
    max_runs: int | None = Field(default=None, ge=1)
    contact_id: uuid.UUID | None = None
    on_missed: _ON_MISSED_LITERAL = "skip"
    concurrency_policy: _CONCURRENCY_LITERAL = "forbid"


class ScheduleUpdate(BaseModel):
    """PATCH /schedules/{id} body — every field optional. NOTE:
    ``active`` is deliberately absent; toggle via ``/pause`` and
    ``/resume``. Server-owned fields are absent so ``extra="forbid"``
    rejects them at 422."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    schedule_kind: _SCHEDULE_KIND_LITERAL | None = None
    config_json: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    starts_at: datetime | None = None
    end_at: datetime | None = None
    max_runs: int | None = Field(default=None, ge=1)
    contact_id: uuid.UUID | None = None
    on_missed: _ON_MISSED_LITERAL | None = None
    concurrency_policy: _CONCURRENCY_LITERAL | None = None


class ScheduleResponse(BaseModel):
    """GET response — full schedule state including server-owned fields.
    ``updated_at`` is the ETag source for the ``If-Match`` optimistic
    lock on subsequent PATCH."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    workflow_id: uuid.UUID
    contact_id: uuid.UUID | None
    name: str
    schedule_kind: str
    config_json: dict[str, Any]
    timezone: str
    starts_at: datetime
    end_at: datetime | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    runs_completed: int
    max_runs: int | None
    active: bool
    deactivation_reason: str | None
    on_missed: str
    concurrency_policy: str
    consecutive_empty_fires: int
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SchedulePreviewRequest(BaseModel):
    """POST /schedules/preview body — Builder-only surface. Computes
    the next 5 fires without persisting anything. Reuses the same
    validation the create path uses so the preview 422 matches the
    save 422."""

    model_config = ConfigDict(extra="forbid")

    schedule_kind: _SCHEDULE_KIND_LITERAL
    config_json: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field(..., max_length=64)
    starts_at: datetime


class SchedulePreviewResponse(BaseModel):
    """Preview response — next 5 fire datetimes in UTC. Empty list
    is a legal outcome (e.g., an interval schedule whose start_at is
    minutes away from ending)."""

    fires: list[datetime]


__all__ = [
    "ABStatsResponse",
    "EventWaitRead",
    "GraphEdge",
    "GraphNode",
    "NodePosition",
    "PairABRequest",
    "RollbackRequest",
    "ScheduleCreate",
    "SchedulePreviewRequest",
    "SchedulePreviewResponse",
    "ScheduleResponse",
    "ScheduleUpdate",
    "WorkflowAnalyticsResponse",
    "WorkflowAnalyticsTotals",
    "WorkflowAnalyticsWindow",
    "WorkflowCreate",
    "WorkflowDailyRateResponse",
    "WorkflowDailyRateRow",
    "WorkflowDiagnosticsEntry",
    "WorkflowDiagnosticsResponse",
    "WorkflowExport",
    "WorkflowFolderCreate",
    "WorkflowFolderRead",
    "WorkflowFunnelRow",
    "WorkflowGraph",
    "WorkflowImportRequest",
    "WorkflowRead",
    "WorkflowRunRead",
    "WorkflowSendMetricRow",
    "WorkflowStepRunRead",
    "WorkflowUpdate",
    "WorkflowVersionDetailRead",
    "WorkflowVersionListResponse",
    "WorkflowVersionSummaryRead",
]
