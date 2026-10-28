"""pipelines + pipeline_stages

Creates the two pipeline-engine tables (tenant-scoped, RLS-on) and the
matching uniqueness constraints. The `(pipeline_id, display_order)`
unique constraint is `INITIALLY DEFERRED` so a same-transaction "trade
places" swap inside the PATCH-stage service does not fail mid-statement.

Revision ID: 0010_pipelines
Revises: 0009_tasks
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0010_pipelines"
down_revision: Union[str, None] = "0009_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="uq_pipelines_org_key"),
    )
    op.create_index("ix_pipelines_org_id", "pipelines", ["org_id"])

    op.create_table(
        "pipeline_stages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_won",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_lost",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id", "key", name="uq_pipeline_stages_pipeline_key"
        ),
    )
    op.create_index(
        "ix_pipeline_stages_org_id", "pipeline_stages", ["org_id"]
    )
    op.create_index(
        "ix_pipeline_stages_order",
        "pipeline_stages",
        ["pipeline_id", "display_order"],
    )

    # `INITIALLY DEFERRED` lets us swap two stages' display_order in the
    # same transaction without the mid-statement violation that an
    # immediate-check constraint would raise. The deferred check runs at
    # COMMIT, by which time both stages have valid distinct values.
    op.execute(
        "ALTER TABLE pipeline_stages "
        "ADD CONSTRAINT uq_pipeline_stages_pipeline_order "
        "UNIQUE (pipeline_id, display_order) DEFERRABLE INITIALLY DEFERRED"
    )

    apply_rls("pipelines")
    apply_rls("pipeline_stages")


def downgrade() -> None:
    drop_rls("pipeline_stages")
    drop_rls("pipelines")
    op.execute(
        "ALTER TABLE pipeline_stages "
        "DROP CONSTRAINT IF EXISTS uq_pipeline_stages_pipeline_order"
    )
    op.drop_index("ix_pipeline_stages_order", table_name="pipeline_stages")
    op.drop_index("ix_pipeline_stages_org_id", table_name="pipeline_stages")
    op.drop_table("pipeline_stages")
    op.drop_index("ix_pipelines_org_id", table_name="pipelines")
    op.drop_table("pipelines")
