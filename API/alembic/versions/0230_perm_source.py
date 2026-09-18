"""Add ``source`` to ``tbl_permissions`` so Core UI surfaces can filter
out pack-registered permission keys (e.g. ``field_visits.*``,
``custom_orders.*``) without hiding them from the packs themselves.

Column is NOT NULL with a server default of ``'core'`` — every existing
row therefore lands as core on upgrade. On the next API startup, the
per-module registration pass rewrites the pack-owned keys to
``pack:<pack_id>`` via the upsert path that now includes source.

Revision ID: 0230_perm_source
Revises:     0229_import_default_source
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0230_perm_source"
down_revision: str | None = "0229_import_default_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_permissions",
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="core",
        ),
    )
    op.create_index(
        "ix_tbl_permissions_source",
        "tbl_permissions",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_permissions_source", table_name="tbl_permissions")
    op.drop_column("tbl_permissions", "source")
