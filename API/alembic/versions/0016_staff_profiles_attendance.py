"""staff_profiles + attendance

Creates the two staff-module tables (tenant-scoped, RLS-on) plus the
`employment_status` Postgres ENUM. `Attendance.hours` is a STORED
generated column computed from `clock_out_at - clock_in_at` so list /
aggregate reads don't recompute on every row.

Revision ID: 0016_staff_profiles_attendance
Revises: 0015_catalog_items
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0016_staff_profiles_attendance"
down_revision: Union[str, None] = "0015_catalog_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("active", "leave", "terminated")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="employment_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "staff_profiles",
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "commission_rate",
            sa.Numeric(5, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "monthly_target",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "rating",
            sa.Numeric(2, 1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "employment_status",
            status_enum,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
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
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_staff_profiles_org_id", "staff_profiles", ["org_id"]
    )

    op.create_table(
        "attendance",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "hours",
            sa.Numeric(8, 2),
            sa.Computed(
                "EXTRACT(EPOCH FROM (clock_out_at - clock_in_at)) / 3600",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_org_id", "attendance", ["org_id"])
    op.create_index(
        "ix_attendance_user_date", "attendance", ["user_id", "date"]
    )

    apply_rls("staff_profiles")
    apply_rls("attendance")


def downgrade() -> None:
    drop_rls("attendance")
    drop_rls("staff_profiles")
    op.drop_index("ix_attendance_user_date", table_name="attendance")
    op.drop_index("ix_attendance_org_id", table_name="attendance")
    op.drop_table("attendance")
    op.drop_index("ix_staff_profiles_org_id", table_name="staff_profiles")
    op.drop_table("staff_profiles")
    postgresql.ENUM(name="employment_status").drop(
        op.get_bind(), checkfirst=True
    )
