"""tbl_user_login: add FurnitureCRM columns

Adds the multi-tenant + RBAC columns FurnitureCRM auth needs onto
`tbl_user_login`, so that this table can become the single login
source of truth (replacing the parallel `users` table).

All new columns are NULL-permissive for the existing legacy row
(USR29684795) which has no email / org / role. A partial unique
index ensures (org_id, email) is unique only when both are set,
so the legacy row is exempted.

`legacy_uuid` is a bridge column: it preserves the UUID identity
of the rows we'll migrate from `users` in 0032, so the existing
`demo_credentials.user_id` UUID FK keeps validating via a join on
`legacy_uuid` (instead of needing to change column types).

This migration is schema-only — no data movement. 0032 will do that.

Revision ID: 0031_tbl_user_login_for_crm
Revises: 0030_demo_credentials
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, UUID


revision: str = "0031_tbl_user_login_for_crm"
down_revision: Union[str, None] = "0030_demo_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tbl_user_login", sa.Column("email", CITEXT(), nullable=True))
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
        sa.Column("legacy_uuid", UUID(as_uuid=True), nullable=True),
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
    op.create_index(
        "uq_tbl_user_login_legacy_uuid",
        "tbl_user_login",
        ["legacy_uuid"],
        unique=True,
        postgresql_where=sa.text("legacy_uuid IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tbl_user_login_legacy_uuid", table_name="tbl_user_login")
    op.drop_index("uq_tbl_user_login_org_email", table_name="tbl_user_login")

    op.drop_constraint(
        "fk_tbl_user_login_role_id", "tbl_user_login", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_tbl_user_login_org_id", "tbl_user_login", type_="foreignkey"
    )

    op.drop_column("tbl_user_login", "updated_at")
    op.drop_column("tbl_user_login", "created_at")
    op.drop_column("tbl_user_login", "legacy_uuid")
    op.drop_column("tbl_user_login", "is_demo")
    op.drop_column("tbl_user_login", "phone")
    op.drop_column("tbl_user_login", "full_name")
    op.drop_column("tbl_user_login", "role_id")
    op.drop_column("tbl_user_login", "org_id")
    op.drop_column("tbl_user_login", "email")
