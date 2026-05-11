"""users_roles_permissions

Creates the four-table RBAC backbone for the layered app:

  roles              tenant-scoped, RLS on
  users              tenant-scoped, RLS on, citext email per-org-unique
  permissions        GLOBAL — shared registry of capability keys
  role_permissions   GLOBAL join table (role.id and permission.id are
                     both unique without tenant scoping)

Revision ID: 0003_users_roles_permissions
Revises: 0002_organizations_rls
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0003_users_roles_permissions"
down_revision: Union[str, None] = "0002_organizations_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "name", name="uq_roles_org_id_name"),
    )
    op.create_index("ix_roles_org_id", "roles", ["org_id"])

    op.create_table(
        "permissions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_permissions_key"),
    )
    op.create_index("ix_permissions_module", "permissions", ["module"])

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "email", name="uq_users_org_id_email"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    # RLS on the two tenant-scoped tables only.
    apply_rls("roles")
    apply_rls("users")


def downgrade() -> None:
    drop_rls("users")
    drop_rls("roles")

    op.drop_table("role_permissions")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_permissions_module", table_name="permissions")
    op.drop_table("permissions")
    op.drop_index("ix_roles_org_id", table_name="roles")
    op.drop_table("roles")
