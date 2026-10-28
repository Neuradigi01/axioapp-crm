"""tbl_organization_members — N:M join between users and orgs.

Step DR.7.1 of the three-table split. Creates the membership table that
will own per-(org, user) state — role grant, status, is_demo flag,
joined_at, ui_preferences — moving those concerns off `tbl_user_login`
where DR.6.1 had stuffed them.

Schema only. No data movement here; DR.7.2 backfills from the
DR.6.1 columns on `tbl_user_login`.

Deviations from the reference architecture:

- `organization_id` is `UUID REFERENCES organizations(id)`, not bigint —
  every other tenant-scoped table in FurnitureCRM keys on UUID org ids.
- `role_id` is `UUID REFERENCES roles(id)` instead of `role TEXT`. The
  layered RBAC (`roles` + `role_permissions` per org) gates the sidebar;
  preserving the FK keeps that machinery working. Reference's `role TEXT`
  shape can be reconsidered if/when we replace the permission-grants
  layer with a static role-name → permissions map.
- No `max_concurrent_chats` column — call-center specific in the
  reference; FurnitureCRM has no equivalent today.

Revision ID: 0033_tbl_organization_members
Revises: 0032_users_to_tbl_user_login
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0033_tbl_organization_members"
down_revision: Union[str, None] = "0032_users_to_tbl_user_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tbl_organization_members",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_member_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "ui_preferences",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_member_id"], ["tbl_user_login.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_member_id",
            name="uq_org_member_user",
        ),
    )
    op.create_index(
        "idx_tbl_org_members_organization_id",
        "tbl_organization_members",
        ["organization_id"],
    )
    op.create_index(
        "idx_tbl_org_members_user_member_id",
        "tbl_organization_members",
        ["user_member_id"],
    )
    # Partial unique: one active membership per user at a time. Matches
    # the reference's `uq_org_members_one_active_per_user`. Lets a user
    # be paused/historical in one org and active in another, but never
    # simultaneously active in two.
    op.create_index(
        "uq_org_members_one_active_per_user",
        "tbl_organization_members",
        ["user_member_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_org_members_one_active_per_user",
        table_name="tbl_organization_members",
    )
    op.drop_index(
        "idx_tbl_org_members_user_member_id",
        table_name="tbl_organization_members",
    )
    op.drop_index(
        "idx_tbl_org_members_organization_id",
        table_name="tbl_organization_members",
    )
    op.drop_table("tbl_organization_members")
