"""workflows A/B test columns

Step 18 of ``tasks/workflows/`` — adds 7 columns to ``tbl_workflows`` so
the operator can pair two drafts as an A/B test, fix a holdback window,
pick a winner-decision metric, and (post-decision) record which
sibling won.

Columns added:

  * ``ab_paired_workflow_id``        UUID FK → tbl_workflows.id (SET NULL)
  * ``ab_test_started_at``           timestamptz nullable
  * ``ab_test_holdback_until``       timestamptz nullable
  * ``ab_test_winner_metric``        enum `ab_winner_metric` default 'goal_conversion'
  * ``ab_test_min_runs_per_variant`` int default 50
  * ``ab_test_winner_workflow_id``   UUID nullable
  * ``ab_test_decided_at``           timestamptz nullable

The pre-existing ``ab_sibling_id`` (Step 1) was the per-row "what
workflow does this enrolment also flow through" pointer. Step 18 keeps
that column for engine-side weighting but introduces
``ab_paired_workflow_id`` as the bidirectional pairing pointer (A.paired
= B.id AND B.paired = A.id) so the service / beat task can resolve the
sibling without a self-join through the engine path.

Reversible — downgrade drops both the columns and the enum.

Revision ID: 0142_workflow_ab_columns
Revises: 0141_whatsapp_web
Create Date: 2026-06-30 09:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0142_workflow_ab_columns"
down_revision: Union[str, None] = "0141_whatsapp_web"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WINNER_METRICS = (
    "goal_conversion",
    "reply_rate",
    "open_rate",
    "custom",
)


def upgrade() -> None:
    metric_enum = postgresql.ENUM(
        *_WINNER_METRICS, name="ab_winner_metric"
    )
    metric_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_paired_workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_holdback_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_winner_metric",
            postgresql.ENUM(
                name="ab_winner_metric", create_type=False
            ),
            nullable=False,
            server_default=sa.text("'goal_conversion'"),
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_min_runs_per_variant",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("50"),
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_winner_workflow_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "ab_test_decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Index for the beat sweep: every hour we look for workflows whose
    # holdback has elapsed but a winner hasn't been recorded yet.
    op.execute(
        "CREATE INDEX ix_workflows_ab_holdback_undecided "
        "ON tbl_workflows (ab_test_holdback_until) "
        "WHERE ab_test_holdback_until IS NOT NULL "
        "AND ab_test_decided_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workflows_ab_holdback_undecided")
    op.drop_column("tbl_workflows", "ab_test_decided_at")
    op.drop_column("tbl_workflows", "ab_test_winner_workflow_id")
    op.drop_column("tbl_workflows", "ab_test_min_runs_per_variant")
    op.drop_column("tbl_workflows", "ab_test_winner_metric")
    op.drop_column("tbl_workflows", "ab_test_holdback_until")
    op.drop_column("tbl_workflows", "ab_test_started_at")
    op.drop_column("tbl_workflows", "ab_paired_workflow_id")
    sa.Enum(name="ab_winner_metric").drop(
        op.get_bind(), checkfirst=True
    )
