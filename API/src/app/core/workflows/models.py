"""Workflows module — SQLAlchemy 2.x async models.

Five tenant-scoped, RLS-on tables back the multi-step workflow
engine. The matching ENUMs are created by migration
``0136_workflows_schema``; the model declarations reference them
with ``create_type=False`` so SQLAlchemy doesn't try to CREATE
TYPE on first metadata-create at test setup.

See :mod:`core.workflows.__init__` for the conceptual map.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped

# --- ENUMs ----------------------------------------------------------------


class WorkflowStatus(str, enum.Enum):
    """Lifecycle of a workflow definition.

    ``draft``    — operator is still composing the graph; the
                   engine never enrols against a draft.
    ``active``   — published + enrolling; the matcher fires for
                   incoming events.
    ``paused``   — temporarily off; existing runs continue but no
                   new enrolments.
    ``archived`` — terminal; the operator can clone but not edit.
    """

    draft = "draft"
    active = "active"
    paused = "paused"
    archived = "archived"


workflow_status_enum = ENUM(
    WorkflowStatus,
    name="workflow_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WorkflowRunStatus(str, enum.Enum):
    """Lifecycle of a single enrolment."""

    pending = "pending"
    running = "running"
    completed = "completed"
    paused = "paused"
    canceled = "canceled"
    errored = "errored"


workflow_run_status_enum = ENUM(
    WorkflowRunStatus,
    name="workflow_run_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WorkflowRunOutcome(str, enum.Enum):
    """Terminal outcome of a finished run."""

    goal_reached = "goal_reached"
    completed = "completed"
    canceled = "canceled"
    errored = "errored"


workflow_run_outcome_enum = ENUM(
    WorkflowRunOutcome,
    name="workflow_run_outcome",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WorkflowStepRunStatus(str, enum.Enum):
    """Lifecycle of a single step execution within a run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    skipped = "skipped"
    errored = "errored"


workflow_step_run_status_enum = ENUM(
    WorkflowStepRunStatus,
    name="workflow_step_run_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class WorkflowReEnrollmentRule(str, enum.Enum):
    """Governs whether the same contact can re-enrol in the same
    workflow more than once.

    ``once``  — first enrolment wins; the matcher's dedupe check
                refuses subsequent events.
    ``daily`` — at most one enrolment per UTC calendar day.
    ``never`` — every matching event creates a fresh run.
    """

    once = "once"
    daily = "daily"
    never = "never"


class ABWinnerMetric(str, enum.Enum):
    """Step-18 A/B-test scoring choice.

    ``goal_conversion`` — `goal_reached` outcome / total runs. The
                          default + the most reliable signal.
    ``reply_rate``      — fraction of runs whose contact replied to a
                          send-action message. v2 polish — currently
                          treated identically to ``goal_conversion``
                          by the picker.
    ``open_rate``       — fraction of runs whose email-send completed
                          + tracked an open. Treated identically to
                          ``goal_conversion`` for now.
    ``custom``          — reserved for v3; falls back to
                          ``goal_conversion``.
    """

    goal_conversion = "goal_conversion"
    reply_rate = "reply_rate"
    open_rate = "open_rate"
    custom = "custom"


workflow_re_enrollment_rule_enum = ENUM(
    WorkflowReEnrollmentRule,
    name="workflow_re_enrollment_rule",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


# --- Models ---------------------------------------------------------------


class WorkflowFolder(Base, TenantScoped):
    """Operator's organisational tree for the Step-13 list page.
    Workflows hang off a folder via ``Workflow.folder_id`` SET
    NULL — deleting a folder doesn't cascade-delete the workflows
    inside it, they just become un-foldered."""

    __tablename__ = "tbl_workflow_folders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflow_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class Workflow(Base, TenantScoped):
    """Workflow definition. The ``graph`` JSONB column carries the
    full ``{nodes, edges}`` shape — the Step-2 validator enforces
    structural rules (single root trigger, no cycles, every node id
    is unique). The denormalised ``enabled_event_types`` list is
    indexed via GIN so the Step-5 trigger matcher can resolve
    "which workflows listen on lead.created?" cheaply without
    walking the JSONB."""

    __tablename__ = "tbl_workflows"
    __table_args__ = (
        Index(
            "ix_workflows_org_status",
            "org_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=sql_text("'Custom'"),
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflow_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        workflow_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("1")
    )
    re_enrollment_rule: Mapped[WorkflowReEnrollmentRule] = mapped_column(
        workflow_re_enrollment_rule_enum,
        nullable=False,
        server_default=sql_text("'once'"),
    )
    is_marketing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    graph: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text('\'{"nodes": [], "edges": []}\'::jsonb'),
    )
    ab_sibling_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflows.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Step 18 — A/B-test pairing columns. ``ab_paired_workflow_id``
    # is the bidirectional sibling pointer set when an operator pairs
    # two drafts; the engine reads it to 50/50-split enrolment.
    # ``ab_sibling_id`` above remains the engine-side "where also to
    # send this contact" column for weighted future extensions.
    ab_paired_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflows.id", ondelete="SET NULL"),
        nullable=True,
    )
    ab_test_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ab_test_holdback_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ab_test_winner_metric: Mapped[ABWinnerMetric] = mapped_column(
        SAEnum(
            ABWinnerMetric,
            name="ab_winner_metric",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=sql_text("'goal_conversion'"),
        default=ABWinnerMetric.goal_conversion,
    )
    ab_test_min_runs_per_variant: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("50")
    )
    ab_test_winner_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    ab_test_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    goal_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_per_run_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    enabled_event_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=sql_text("ARRAY[]::text[]"),
    )
    # Step 19 — list-page mini-stats. Refreshed every 5 minutes by
    # ``tasks.refresh_workflow_cached_counters``; the full analytics
    # endpoint queries live so these are best-effort only.
    cached_running_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    cached_completed_today_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )

    @property
    def graph_nodes_by_id(self) -> dict[str, dict[str, Any]]:
        """In-Python helper — maps node id → node dict for fast
        engine lookup. Not a separate column; computed off the
        ``graph`` JSONB."""
        nodes = (self.graph or {}).get("nodes") or []
        return {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}


class WorkflowVersion(Base, TenantScoped):
    """Append-only version history. Step 17 writes one row per
    published edit so operators can diff / revert. The original
    workflow row's ``graph`` always holds the live (published or
    draft) version; this table is the audit trail."""

    __tablename__ = "tbl_workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version",
            name="uq_workflow_versions_workflow_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class WorkflowRun(Base, TenantScoped):
    """One enrolment of a workflow — typically per contact. The
    engine reads ``current_node_id`` to decide which node to
    execute next; the per-run ``state`` JSONB accumulates variables
    emitted by record-update actions for downstream nodes to read.

    Three indexes back the three hot reads:
      * analytics: ``(org_id, workflow_id, started_at DESC)``
      * scheduler sweep: partial
        ``(org_id, status, next_step_at) WHERE status='pending'``
      * re-enrolment dedupe: ``(workflow_id, contact_id,
        started_at DESC)``"""

    __tablename__ = "tbl_workflow_runs"
    __table_args__ = (
        Index(
            "ix_workflow_runs_org_workflow_started",
            "org_id",
            "workflow_id",
            sql_text("started_at DESC"),
        ),
        Index(
            "ix_workflow_runs_workflow_contact_started",
            "workflow_id",
            "contact_id",
            sql_text("started_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflows.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        workflow_run_status_enum,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    current_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[WorkflowRunOutcome | None] = mapped_column(
        workflow_run_outcome_enum, nullable=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    next_step_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStepRun(Base, TenantScoped):
    """Append-only per-node audit log. One row per node
    execution within a run; Step 19's run-history UI groups by
    ``run_id`` and orders by ``step_index``. ``output_edge_label``
    captures which outbound edge the branch / switch chose;
    ``skip_reason`` records the compliance-gate / opt-out / quiet-
    hours decision the engine made."""

    __tablename__ = "tbl_workflow_step_runs"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "step_index",
            name="uq_workflow_step_runs_run_step_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WorkflowStepRunStatus] = mapped_column(
        workflow_step_run_status_enum,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_edge_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowEventWait(Base, TenantScoped):
    """Step-11 wait-for-event registry. One row per parked
    ``flow_control.wait_for_event`` node. The trigger handler
    (Step 5) checks this table on every published event + resumes
    matching runs on the ``event_received`` outbound edge; the
    beat sweep handles the timeout path.

    ``contact_id`` is nullable — when set, only that specific
    contact's event resumes; when null, ANY event of the type
    resumes (useful for org-wide events like ``time.daily_tick``).

    Cascade-delete on parent run so canceling a run cleans up its
    parked waits automatically."""

    __tablename__ = "tbl_workflow_event_waits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


__all__ = [
    "ABWinnerMetric",
    "Workflow",
    "WorkflowEventWait",
    "WorkflowFolder",
    "WorkflowReEnrollmentRule",
    "WorkflowRun",
    "WorkflowRunOutcome",
    "WorkflowRunStatus",
    "WorkflowStatus",
    "WorkflowStepRun",
    "WorkflowStepRunStatus",
    "WorkflowVersion",
    "workflow_re_enrollment_rule_enum",
    "workflow_run_outcome_enum",
    "workflow_run_status_enum",
    "workflow_status_enum",
    "workflow_step_run_status_enum",
]
