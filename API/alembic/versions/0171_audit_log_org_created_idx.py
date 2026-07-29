"""tbl_audit_logs — composite (org_id, created_at DESC) index.

The dashboard's ``_recent_activity`` (and, going forward, any per-org
audit reader) fetches by:

    SELECT * FROM tbl_audit_logs
     WHERE org_id = :org_id
     ORDER BY created_at DESC
     LIMIT :n

The existing schema has ``org_id`` and ``created_at`` indexed
separately. On mixed workloads Postgres picks one and does an in-memory
sort/filter on the rest; on a per-tenant "latest 40" query the sort
dominates and the plan degrades with row count. A composite
``(org_id, created_at DESC)`` matches the query shape end-to-end so it
becomes an index-only forward scan bounded by LIMIT — same latency at
40 rows and at 40 million.

Revision ID: 0171_audit_log_org_created_idx
Revises:     0170_device_tokens_uniq
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0171_audit_log_org_created_idx"
down_revision = "0170_device_tokens_uniq"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_audit_logs_org_created_desc"


def upgrade() -> None:
    # `CONCURRENTLY` would let this land without locking the write
    # path, but Alembic's default transactional DDL blocks it; the
    # `tbl_audit_logs` table is small enough per deploy that a
    # blocking CREATE INDEX finishes in seconds. Emit as a bare
    # ``CREATE INDEX`` so both dev and CI upgrade paths behave the
    # same way.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
            ON tbl_audit_logs (org_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
