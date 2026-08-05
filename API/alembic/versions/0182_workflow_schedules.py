"""Workflow schedules (``tasks/workflow-scheduling`` Step 1).

NEW table ``tbl_workflow_schedules`` — an independent, additive
firing mechanism attached to any workflow. A schedule fires
independently of the workflow's own event trigger; both mechanisms
can coexist on the same workflow (e.g. seeded "Birthday Wish"
firing on ``contact.birthday`` AND on Monday 09:00).

Schema:

  id                       UUID PK
  org_id                   UUID FK tbl_organizations.id CASCADE
  workflow_id              UUID FK tbl_workflows.id      CASCADE
  contact_id               UUID FK tbl_contacts.id       SET NULL
  name                     VARCHAR(200)
  schedule_kind            workflow_schedule_kind
  config_json              JSONB
  timezone                 VARCHAR(64) default 'UTC'
  starts_at                TIMESTAMPTZ
  end_at                   TIMESTAMPTZ  nullable
  next_run_at              TIMESTAMPTZ  nullable
  last_run_at              TIMESTAMPTZ  nullable
  runs_completed           INT default 0
  max_runs                 INT nullable
  active                   BOOL default true
  deactivation_reason      workflow_schedule_deactivation_reason  nullable
  on_missed                workflow_schedule_on_missed             default 'skip'
  concurrency_policy       workflow_schedule_concurrency           default 'forbid'
  consecutive_empty_fires  INT default 0
  created_by_user_id       UUID FK tbl_users.id SET NULL
  created_at               TIMESTAMPTZ default now()
  updated_at               TIMESTAMPTZ default now()

Indexes:
  - ``ix_schedules_next_run_due`` PARTIAL ``(next_run_at) WHERE active = true``
    — sweep hot path. Partial predicate keeps the index bounded
    (inactive rows dominate at steady state).
  - ``ix_schedules_org_workflow`` ``(org_id, workflow_id)`` — list-
    schedules-for-workflow hot path (Builder attach panel + list-page
    count subquery).

RLS: matches every other tenant-scoped table — the
``current_setting('app.current_org_id')`` gate. Sweep task
sets the GUC per-row before dispatching (Step 2).

ALSO adds three audit columns to ``tbl_workflow_runs``:

  trigger_kind          workflow_run_trigger_kind NOT NULL default 'event'
  trigger_source_id     UUID nullable
  triggered_by_user_id  UUID FK tbl_users.id SET NULL nullable

Existing runs are backfilled to ``trigger_kind = 'event'`` via the
NOT NULL default — no explicit UPDATE needed.

Note: ``tbl_organizations.timezone`` is already NOT NULL with default
``'Asia/Kolkata'`` (see 0135). No NULL-backfill needed — the earlier
plan's step was a memory-vs-current-code miss caught during Step 1
implementation.

Chains after ``0181_user_email_all_events``. Reversible.

Revision ID: 0182_workflow_schedules
Revises: 0181_user_email_all_events
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0182_workflow_schedules"
down_revision: str | None = "0181_user_email_all_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- enum names (kept as top-level constants so upgrade + downgrade agree) --

_ENUM_SCHEDULE_KIND = "workflow_schedule_kind"
_ENUM_ON_MISSED = "workflow_schedule_on_missed"
_ENUM_CONCURRENCY = "workflow_schedule_concurrency"
_ENUM_DEACTIVATION_REASON = "workflow_schedule_deactivation_reason"
_ENUM_TRIGGER_KIND = "workflow_run_trigger_kind"


def upgrade() -> None:
    # --- 1. Create the enum types --------------------------------------
    op.execute(
        f"CREATE TYPE {_ENUM_SCHEDULE_KIND} AS ENUM "
        "('once', 'daily', 'weekly', 'monthly', 'interval', 'cron')"
    )
    op.execute(
        f"CREATE TYPE {_ENUM_ON_MISSED} AS ENUM "
        "('skip', 'run_once', 'backfill_all')"
    )
    op.execute(
        f"CREATE TYPE {_ENUM_CONCURRENCY} AS ENUM "
        "('allow', 'forbid', 'replace')"
    )
    op.execute(
        f"CREATE TYPE {_ENUM_DEACTIVATION_REASON} AS ENUM ("
        "'manual', 'ended', 'max_runs', 'end_at', 'consecutive_empty', "
        "'recurrence_timeout', 'recurrence_invalid', 'contact_deleted', "
        "'admin_edit_past_end_at'"
        ")"
    )
    op.execute(
        f"CREATE TYPE {_ENUM_TRIGGER_KIND} AS ENUM "
        "('event', 'schedule', 'manual')"
    )

    # --- 2. Create tbl_workflow_schedules ------------------------------
    op.create_table(
        "tbl_workflow_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "schedule_kind",
            postgresql.ENUM(
                name=_ENUM_SCHEDULE_KIND, create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "config_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "runs_completed",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("max_runs", sa.Integer, nullable=True),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "deactivation_reason",
            postgresql.ENUM(
                name=_ENUM_DEACTIVATION_REASON, create_type=False
            ),
            nullable=True,
        ),
        sa.Column(
            "on_missed",
            postgresql.ENUM(name=_ENUM_ON_MISSED, create_type=False),
            nullable=False,
            server_default=sa.text("'skip'"),
        ),
        sa.Column(
            "concurrency_policy",
            postgresql.ENUM(name=_ENUM_CONCURRENCY, create_type=False),
            nullable=False,
            server_default=sa.text("'forbid'"),
        ),
        sa.Column(
            "consecutive_empty_fires",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        # Soft reference (no FK) — matches the rest of the workflows
        # module's user-id columns; avoids user-table churn cascading
        # into schedule history.
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- 3. Indexes ----------------------------------------------------
    # Sweep hot path — partial on active=true keeps the index bounded.
    op.create_index(
        "ix_schedules_next_run_due",
        "tbl_workflow_schedules",
        ["next_run_at"],
        postgresql_where=sa.text("active = true"),
    )
    op.create_index(
        "ix_schedules_org_workflow",
        "tbl_workflow_schedules",
        ["org_id", "workflow_id"],
    )

    # --- 4. RLS --------------------------------------------------------
    op.execute("ALTER TABLE tbl_workflow_schedules ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tbl_workflow_schedules_tenant_isolation
            ON tbl_workflow_schedules
            USING (org_id::text = current_setting('app.current_org_id', true))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
        """
    )

    # --- 5. Audit columns on tbl_workflow_runs -------------------------
    # trigger_kind: server_default = 'event' backfills existing rows
    # atomically (no separate UPDATE needed). Column then becomes
    # NOT NULL immediately.
    op.add_column(
        "tbl_workflow_runs",
        sa.Column(
            "trigger_kind",
            postgresql.ENUM(name=_ENUM_TRIGGER_KIND, create_type=False),
            nullable=False,
            server_default=sa.text("'event'"),
        ),
    )
    op.add_column(
        "tbl_workflow_runs",
        sa.Column(
            "trigger_source_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_workflow_runs",
        sa.Column(
            "triggered_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Reverse in strict LIFO order — indexes, then tables, then
    # enum types.

    # --- 5. Audit columns off tbl_workflow_runs ------------------------
    op.drop_column("tbl_workflow_runs", "triggered_by_user_id")
    op.drop_column("tbl_workflow_runs", "trigger_source_id")
    op.drop_column("tbl_workflow_runs", "trigger_kind")

    # --- 4. RLS --------------------------------------------------------
    op.execute(
        "DROP POLICY IF EXISTS tbl_workflow_schedules_tenant_isolation "
        "ON tbl_workflow_schedules"
    )

    # --- 3. Indexes ----------------------------------------------------
    op.drop_index(
        "ix_schedules_org_workflow",
        table_name="tbl_workflow_schedules",
    )
    op.drop_index(
        "ix_schedules_next_run_due",
        table_name="tbl_workflow_schedules",
    )

    # --- 2. Table ------------------------------------------------------
    op.drop_table("tbl_workflow_schedules")

    # --- 1. Enum types -------------------------------------------------
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_TRIGGER_KIND}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_DEACTIVATION_REASON}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_CONCURRENCY}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_ON_MISSED}")
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_SCHEDULE_KIND}")
