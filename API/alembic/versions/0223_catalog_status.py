"""catalog_status — publish state machine on tbl_catalog_items.

Adds ``status`` (draft/published/unpublished/archived), ``published_at``,
and ``archived_at`` so catalog items can be shared publicly only after
the operator explicitly publishes. Mirrors the property module's
state-machine shape (minus the terminal ``sold`` state — products aren't
one-off assets).

Backfill on upgrade:
  * ``is_active=true``  → ``status='published'`` + ``published_at=now()``
  * ``is_active=false`` → ``status='archived'``  + ``archived_at=now()``

New permissions ``catalog.publish`` + ``catalog.archive`` are inserted
and granted to Owner + Admin roles on every existing org (following
the 0221 pattern). Employee stays read-only.

Revision ID: 0223_catalog_status
Revises:     0222_calls_created_by
Create Date: 2026-09-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0223_catalog_status"
down_revision: Union[str, None] = "0222_calls_created_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUSES = ("draft", "published", "unpublished", "archived")
_PERM_KEYS = (
    ("catalog.publish", "catalog", "Publish/unpublish catalog products (Owner/Admin)."),
    ("catalog.archive", "catalog", "Archive/unarchive catalog products (Owner/Admin)."),
)
_PERM_ROLES = ("Owner", "Admin")


def upgrade() -> None:
    op.add_column(
        "tbl_catalog_items",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
    )
    op.add_column(
        "tbl_catalog_items",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_catalog_items",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_catalog_items_status",
        "tbl_catalog_items",
        f"status IN {tuple(_STATUSES)}",
    )

    # Backfill existing rows: is_active=true → published, else archived.
    op.execute(
        "UPDATE tbl_catalog_items "
        "SET status = 'published', published_at = now() "
        "WHERE is_active = true"
    )
    op.execute(
        "UPDATE tbl_catalog_items "
        "SET status = 'archived', archived_at = now() "
        "WHERE is_active = false"
    )

    op.create_index(
        "ix_catalog_items_org_status",
        "tbl_catalog_items",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_catalog_items_org_published",
        "tbl_catalog_items",
        ["org_id", "published_at"],
        postgresql_where=sa.text("status = 'published'"),
    )

    # Register the two new permission keys + grant to Owner + Admin
    # on every existing org (follows 0221's pattern).
    for key, module, desc in _PERM_KEYS:
        op.execute(
            f"INSERT INTO tbl_permissions (key, module, description) "
            f"VALUES ('{key}', '{module}', '{desc}') "
            f"ON CONFLICT (key) DO NOTHING"
        )
        for role in _PERM_ROLES:
            op.execute(
                f"INSERT INTO tbl_role_permissions (role_id, permission_id) "
                f"SELECT r.id, p.id FROM tbl_roles r CROSS JOIN tbl_permissions p "
                f"WHERE r.name = '{role}' AND p.key = '{key}' "
                f"ON CONFLICT DO NOTHING"
            )


def downgrade() -> None:
    for key, _module, _desc in _PERM_KEYS:
        for role in _PERM_ROLES:
            op.execute(
                f"DELETE FROM tbl_role_permissions "
                f"WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role}') "
                f"  AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{key}')"
            )
        op.execute(f"DELETE FROM tbl_permissions WHERE key = '{key}'")

    op.drop_index("ix_catalog_items_org_published", table_name="tbl_catalog_items")
    op.drop_index("ix_catalog_items_org_status", table_name="tbl_catalog_items")
    op.drop_constraint("ck_catalog_items_status", "tbl_catalog_items", type_="check")
    op.drop_column("tbl_catalog_items", "archived_at")
    op.drop_column("tbl_catalog_items", "published_at")
    op.drop_column("tbl_catalog_items", "status")
