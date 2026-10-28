"""leads.lead_score + lead_scoring_rules + keyset indexes (Step 5).

Adds the operator-defined lead-scoring engine to the leads module:

  - ``leads.lead_score INTEGER NOT NULL DEFAULT 0`` — rule-engine
    output, clamped ``[0, 100]`` at write time.
  - ``lead_scoring_rules`` — one row per active rule contributing to
    a lead's score. ``condition`` JSONB carries a filter-DSL fragment.
    Per-org via ``org_id`` + RLS.
  - Composite keyset indexes on ``(org_id, <sort_col>, id)`` for the
    cursor-paginated GET /leads list. Without these the keyset
    `(sort_col, id) < (cursor.v, cursor.id)` bound goes back to a seq
    scan on multi-thousand-row tables.

No backfill required: ``lead_score`` defaults to 0; the next write to
each lead (or the hourly Celery sweep) repopulates it from the rule set.

Revision ID: 0070_leads_scoring
Revises: 0069_wa_rate_limit
Create Date: 2026-06-01 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0070_leads_scoring"
down_revision: Union[str, None] = "0069_wa_rate_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- leads.lead_score ---
    op.add_column(
        "leads",
        sa.Column(
            "lead_score",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # --- keyset cursor indexes ---
    # Default sort: created_at DESC. Secondary key on id keeps the
    # (sort_col, id) bound deterministic when many rows share the same
    # created_at to the millisecond.
    op.create_index(
        "ix_leads_org_created_id",
        "leads",
        ["org_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    # Last-activity sort with NULLS LAST so never-touched leads sink.
    op.create_index(
        "ix_leads_org_last_activity_id",
        "leads",
        [
            "org_id",
            sa.text("last_activity_at DESC NULLS LAST"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_leads_org_score_id",
        "leads",
        ["org_id", sa.text("lead_score DESC"), sa.text("id DESC")],
    )

    # --- lead_scoring_rules ---
    op.create_table(
        "lead_scoring_rules",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("condition", JSONB(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "points BETWEEN -100 AND 100",
            name="ck_lead_scoring_rules_points_range",
        ),
    )
    op.create_index(
        "ix_lead_scoring_rules_org_active",
        "lead_scoring_rules",
        ["org_id", "active"],
    )

    apply_rls("lead_scoring_rules")


def downgrade() -> None:
    drop_rls("lead_scoring_rules")
    op.drop_index(
        "ix_lead_scoring_rules_org_active",
        table_name="lead_scoring_rules",
    )
    op.drop_table("lead_scoring_rules")

    op.drop_index("ix_leads_org_score_id", table_name="leads")
    op.drop_index("ix_leads_org_last_activity_id", table_name="leads")
    op.drop_index("ix_leads_org_created_id", table_name="leads")
    op.drop_column("leads", "lead_score")
