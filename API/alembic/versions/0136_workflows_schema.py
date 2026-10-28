"""Workflows foundation — five tables + enums + RLS (``tasks/workflows``
Step 1).

Module C of the three-track plan (Templates → Automation → Workflows).
The automation-engine track ships single-event triggers; this track
adds multi-step branching flowcharts with conditions, delays, and
graph-based step orchestration.

Five tables land here:

  * ``tbl_workflow_folders`` — operator's organisational tree for the
    Workflows list page (Step 13).
  * ``tbl_workflows`` — the workflow definition itself: name, status,
    `graph` JSONB ({nodes, edges}), enrolment rules.
  * ``tbl_workflow_versions`` — append-only version history; Step 17
    writes one row per published edit so operators can compare /
    revert.
  * ``tbl_workflow_runs`` — one row per enrolment (typically per
    contact); tracks ``current_node_id`` + ``state`` JSONB for the
    engine's per-run accumulator.
  * ``tbl_workflow_step_runs`` — append-only per-node audit + run
    history; Steps 4 + 19 write one row each time the engine touches
    a node.

Five ENUMs back the status fields:

  * ``workflow_status`` (draft / active / paused / archived)
  * ``workflow_run_status`` (pending / running / completed / paused /
    canceled / errored)
  * ``workflow_run_outcome`` (goal_reached / completed / canceled /
    errored)
  * ``workflow_step_run_status`` (pending / running / completed /
    skipped / errored)
  * ``workflow_re_enrollment_rule`` (once / daily / never)

RLS policies match every other tenant-scoped table in the build —
``org_id = current_setting('app.current_org_id')`` gate.

Chains after ``0135_deliverability_tables``. Reversible (FK-safe
drop order on downgrade).

Revision ID: 0136_workflows_schema
Revises: 0135_deliverability_tables
Create Date: 2026-06-29 17:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0136_workflows_schema"
down_revision: Union[str, None] = "0135_deliverability_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- ENUMs ----------------------------------------------------------------
    workflow_status = postgresql.ENUM(
        "draft",
        "active",
        "paused",
        "archived",
        name="workflow_status",
        create_type=True,
    )
    workflow_status.create(bind, checkfirst=True)

    workflow_run_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "paused",
        "canceled",
        "errored",
        name="workflow_run_status",
        create_type=True,
    )
    workflow_run_status.create(bind, checkfirst=True)

    workflow_run_outcome = postgresql.ENUM(
        "goal_reached",
        "completed",
        "canceled",
        "errored",
        name="workflow_run_outcome",
        create_type=True,
    )
    workflow_run_outcome.create(bind, checkfirst=True)

    workflow_step_run_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "skipped",
        "errored",
        name="workflow_step_run_status",
        create_type=True,
    )
    workflow_step_run_status.create(bind, checkfirst=True)

    workflow_re_enrollment_rule = postgresql.ENUM(
        "once",
        "daily",
        "never",
        name="workflow_re_enrollment_rule",
        create_type=True,
    )
    workflow_re_enrollment_rule.create(bind, checkfirst=True)

    # --- tbl_workflow_folders -------------------------------------------------
    op.create_table(
        "tbl_workflow_folders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "parent_folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflow_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Case-insensitive name uniqueness within an org + parent. Allows
    # two "Welcome" folders at the root and inside "Marketing".
    op.execute(
        """
        CREATE UNIQUE INDEX uq_workflow_folders_org_lower_name_parent
            ON tbl_workflow_folders (
                org_id,
                lower(name),
                COALESCE(parent_folder_id, '00000000-0000-0000-0000-000000000000')
            )
        """
    )

    # --- tbl_workflows --------------------------------------------------------
    op.create_table(
        "tbl_workflows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'Custom'"),
        ),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflow_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="workflow_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "re_enrollment_rule",
            postgresql.ENUM(
                name="workflow_re_enrollment_rule",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'once'"),
        ),
        sa.Column(
            "is_marketing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "graph",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{\"nodes\": [], \"edges\": []}'::jsonb"),
        ),
        sa.Column(
            "ab_sibling_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("goal_node_id", sa.Text(), nullable=True),
        sa.Column(
            "cost_per_run_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enabled_event_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_workflows_org_lower_name
            ON tbl_workflows (org_id, lower(name))
        """
    )
    # Index the denormalised event-type list so the Step-5 matcher
    # can find every workflow listening on a given event_type
    # without scanning the JSONB graph.
    op.create_index(
        "ix_workflows_event_types_gin",
        "tbl_workflows",
        ["enabled_event_types"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_workflows_org_status",
        "tbl_workflows",
        ["org_id", "status"],
    )

    # --- tbl_workflow_versions ------------------------------------------------
    op.create_table(
        "tbl_workflow_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "graph",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "version",
            name="uq_workflow_versions_workflow_version",
        ),
    )

    # --- tbl_workflow_runs ----------------------------------------------------
    op.create_table(
        "tbl_workflow_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflows.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trigger_event_id", sa.Text(), nullable=True),
        sa.Column(
            "trigger_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="workflow_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("current_node_id", sa.Text(), nullable=True),
        sa.Column(
            "outcome",
            postgresql.ENUM(
                name="workflow_run_outcome",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "next_step_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workflow_runs_org_workflow_started",
        "tbl_workflow_runs",
        ["org_id", "workflow_id", sa.text("started_at DESC")],
    )
    op.execute(
        """
        CREATE INDEX ix_workflow_runs_pending_sweep
            ON tbl_workflow_runs (org_id, status, next_step_at)
            WHERE status = 'pending'
        """
    )
    op.create_index(
        "ix_workflow_runs_workflow_contact_started",
        "tbl_workflow_runs",
        ["workflow_id", "contact_id", sa.text("started_at DESC")],
    )

    # --- tbl_workflow_step_runs ----------------------------------------------
    op.create_table(
        "tbl_workflow_step_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="workflow_step_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("output_edge_label", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "run_id",
            "step_index",
            name="uq_workflow_step_runs_run_step_index",
        ),
    )
    op.execute(
        """
        CREATE INDEX ix_workflow_step_runs_org_started_errored
            ON tbl_workflow_step_runs (org_id, started_at DESC)
            WHERE status = 'errored'
        """
    )

    # --- RLS policies ---------------------------------------------------------
    for table in (
        "tbl_workflow_folders",
        "tbl_workflows",
        "tbl_workflow_versions",
        "tbl_workflow_runs",
        "tbl_workflow_step_runs",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )


def downgrade() -> None:
    # Drop in FK-safe order: step_runs → runs → versions → workflows
    # → folders. Each policy + index goes down with its table.
    for table in (
        "tbl_workflow_step_runs",
        "tbl_workflow_runs",
        "tbl_workflow_versions",
        "tbl_workflows",
        "tbl_workflow_folders",
    ):
        op.execute(
            f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}"
        )

    op.drop_index(
        "ix_workflow_step_runs_org_started_errored",
        table_name="tbl_workflow_step_runs",
    )
    op.drop_table("tbl_workflow_step_runs")

    op.drop_index(
        "ix_workflow_runs_workflow_contact_started",
        table_name="tbl_workflow_runs",
    )
    op.drop_index(
        "ix_workflow_runs_pending_sweep",
        table_name="tbl_workflow_runs",
    )
    op.drop_index(
        "ix_workflow_runs_org_workflow_started",
        table_name="tbl_workflow_runs",
    )
    op.drop_table("tbl_workflow_runs")

    op.drop_table("tbl_workflow_versions")

    op.drop_index("ix_workflows_org_status", table_name="tbl_workflows")
    op.drop_index("ix_workflows_event_types_gin", table_name="tbl_workflows")
    op.drop_index("uq_workflows_org_lower_name", table_name="tbl_workflows")
    op.drop_table("tbl_workflows")

    op.drop_index(
        "uq_workflow_folders_org_lower_name_parent",
        table_name="tbl_workflow_folders",
    )
    op.drop_table("tbl_workflow_folders")

    for enum_name in (
        "workflow_re_enrollment_rule",
        "workflow_step_run_status",
        "workflow_run_outcome",
        "workflow_run_status",
        "workflow_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
