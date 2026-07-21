"""Add `walk_in` to lead_source enum + walk-in hot-path indexes.

Two additive schema changes needed for the walk-ins bug batch:

1. ``ALTER TYPE lead_source ADD VALUE 'walk_in'`` so
   ``convert_walk_in_to_lead`` can stamp the correct provenance on
   the fresh Lead. Previously fell back to `manual`, muddying
   attribution reports.

2. Three indexes on ``tbl_walk_ins``:
   * ``ix_walk_ins_updated_at`` — rollup 30d window scans by
     ``updated_at``; without an index every KPI refresh full-scans.
   * ``ix_walk_ins_last_activity_at`` — supports the
     ``last_activity_at`` sort option in the list endpoint (NULLS
     LAST ordering).
   * ``ix_walk_ins_linked_lead_id`` — reverse lookup used by the
     lead-detail "originated from walk-in" panel (partial index,
     only rows where the link exists).

Downgrade drops the indexes cleanly. The enum value is not removed
on downgrade (Postgres does not support ``ALTER TYPE ... DROP VALUE``
in-place — the correct rollback path is a manual re-create, out of
scope for this migration).

Revision ID: 0167_walk_in_lead_source
Revises:     0166_lead_import_warnings_report
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0167_walk_in_lead_source"
down_revision: str | None = "0166_lead_import_warnings_report"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block
    # in older Postgres versions; PG 12+ allows it. Autocommit for
    # safety across environments.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE lead_source ADD VALUE IF NOT EXISTS 'walk_in'")

    op.create_index(
        "ix_walk_ins_updated_at",
        "tbl_walk_ins",
        ["updated_at"],
    )
    op.create_index(
        "ix_walk_ins_last_activity_at",
        "tbl_walk_ins",
        ["last_activity_at"],
    )
    op.create_index(
        "ix_walk_ins_linked_lead_id",
        "tbl_walk_ins",
        ["linked_lead_id"],
        postgresql_where="linked_lead_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_walk_ins_linked_lead_id", table_name="tbl_walk_ins")
    op.drop_index("ix_walk_ins_last_activity_at", table_name="tbl_walk_ins")
    op.drop_index("ix_walk_ins_updated_at", table_name="tbl_walk_ins")
