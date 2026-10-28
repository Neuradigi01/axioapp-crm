"""Drop DR.6.1 columns from tbl_user_login

Final schema step of the three-table split. The DR.6.1 columns
(email, org_id, role_id, full_name, phone, is_demo, created_at,
updated_at) were lifted to `tbl_user_info` (email / full_name → first
+ last / phone → mobile_no) and `tbl_organization_members` (org_id /
role_id / is_demo / joined_at) by DR.7.2. The User model stopped
reading those columns in DR.7.3; this migration removes the now-dead
schema.

`legacy_uuid` is kept on `tbl_user_login` — it's the UUID identity
that every cross-table `user_id` FK (audit_logs, auth_sessions,
staff_sessions, staff_profiles, demo_credentials) and the JWT `sub`
reference. Retargeting those FKs to `tbl_user_login.id` (bigint) is
out of scope for DR.7; track on the soak checklist.

After this migration, `tbl_user_login` matches the reference
architecture's shape:
  - id, user_id (text), password, two_factor_*, is_active
  - plus: `legacy_uuid` (transitional column kept for FK resolution)

Revision ID: 0035_drop_dr6_cols
Revises: 0034_backfill_info_and_members
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, UUID


revision: str = "0035_drop_dr6_cols"
down_revision: Union[str, None] = "0034_backfill_info_and_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "uq_tbl_user_login_org_email", table_name="tbl_user_login"
    )
    op.drop_constraint(
        "fk_tbl_user_login_role_id", "tbl_user_login", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_tbl_user_login_org_id", "tbl_user_login", type_="foreignkey"
    )
    op.drop_column("tbl_user_login", "updated_at")
    op.drop_column("tbl_user_login", "created_at")
    op.drop_column("tbl_user_login", "is_demo")
    op.drop_column("tbl_user_login", "phone")
    op.drop_column("tbl_user_login", "full_name")
    op.drop_column("tbl_user_login", "role_id")
    op.drop_column("tbl_user_login", "org_id")
    op.drop_column("tbl_user_login", "email")


def downgrade() -> None:
    # Re-create the columns so a downgrade restores the
    # tbl_user_login shape DR.6.1 produced. Data is NOT restored —
    # the actual values live on `tbl_user_info` and
    # `tbl_organization_members` after DR.7.2. If you need a
    # write-back, do it explicitly after this downgrade runs.
    op.add_column(
        "tbl_user_login", sa.Column("email", CITEXT(), nullable=True)
    )
    op.add_column(
        "tbl_user_login",
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column("role_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column("full_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column("phone", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "tbl_user_login",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_tbl_user_login_org_id",
        "tbl_user_login",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_tbl_user_login_role_id",
        "tbl_user_login",
        "roles",
        ["role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_tbl_user_login_org_email",
        "tbl_user_login",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL AND org_id IS NOT NULL"),
    )
