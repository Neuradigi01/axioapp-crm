"""staff_sessions

One-table migration for the staff-portal JWT pool. Same revocation
shape as `auth_sessions` but a separate physical table so the two
session surfaces never share rows.

Tenant-scoped + RLS-on (every row carries `org_id`).

Revision ID: 0017_staff_sessions
Revises: 0016_staff_profiles_attendance
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0017_staff_sessions"
down_revision: Union[str, None] = "0016_staff_profiles_attendance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_sessions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("ua", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_staff_sessions_org_id", "staff_sessions", ["org_id"]
    )
    op.create_index(
        "ix_staff_sessions_user_id", "staff_sessions", ["user_id"]
    )
    op.create_index(
        "ix_staff_sessions_expires_at", "staff_sessions", ["expires_at"]
    )

    apply_rls("staff_sessions")


def downgrade() -> None:
    drop_rls("staff_sessions")
    op.drop_index("ix_staff_sessions_expires_at", table_name="staff_sessions")
    op.drop_index("ix_staff_sessions_user_id", table_name="staff_sessions")
    op.drop_index("ix_staff_sessions_org_id", table_name="staff_sessions")
    op.drop_table("staff_sessions")
