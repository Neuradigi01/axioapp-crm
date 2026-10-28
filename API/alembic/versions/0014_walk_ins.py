"""walk_ins

Creates the `walk_ins` table (tenant-scoped, RLS-on) with the
`walk_in_status` Postgres ENUM and a STORED generated column for
`duration_min` (NULL until checkout).

Indexed for:

- ``ix_walk_ins_org_time_in``      — "today's walk-ins" reads.
- ``ix_walk_ins_assigned_status``  — "my open walk-ins" reads.
- ``ix_walk_ins_contact_id``       — joins back to contacts.

Revision ID: 0014_walk_ins
Revises: 0013_notifications
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0014_walk_ins"
down_revision: Union[str, None] = "0013_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("browsing", "interested", "follow_up", "converted", "left")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="walk_in_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "walk_ins",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "time_in",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("time_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "duration_min",
            sa.Numeric(10, 2),
            sa.Computed(
                "EXTRACT(EPOCH FROM (time_out - time_in)) / 60",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("requirement", sa.Text(), nullable=True),
        sa.Column("budget", sa.Numeric(14, 2), nullable=True),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'browsing'"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "custom_data",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
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
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_walk_ins_org_id", "walk_ins", ["org_id"])
    op.create_index("ix_walk_ins_contact_id", "walk_ins", ["contact_id"])
    op.create_index(
        "ix_walk_ins_org_time_in", "walk_ins", ["org_id", "time_in"]
    )
    op.create_index(
        "ix_walk_ins_assigned_status", "walk_ins", ["assigned_to_id", "status"]
    )

    apply_rls("walk_ins")


def downgrade() -> None:
    drop_rls("walk_ins")
    op.drop_index("ix_walk_ins_assigned_status", table_name="walk_ins")
    op.drop_index("ix_walk_ins_org_time_in", table_name="walk_ins")
    op.drop_index("ix_walk_ins_contact_id", table_name="walk_ins")
    op.drop_index("ix_walk_ins_org_id", table_name="walk_ins")
    op.drop_table("walk_ins")
    postgresql.ENUM(name="walk_in_status").drop(
        op.get_bind(), checkfirst=True
    )
