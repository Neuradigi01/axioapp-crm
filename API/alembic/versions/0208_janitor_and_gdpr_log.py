"""Add janitor-heartbeat + GDPR deletion log tables, and retention_days to assistants
(``tasks/ai-assistants`` Step 17).

Adds two new tables:

  * ``tbl_janitor_heartbeats`` — global (no org_id) monitor state for
    Celery beat tasks. One row per task type. Enables health
    endpoint to track last successful run + status.
  * ``tbl_gdpr_deletion_log`` — audit trail for GDPR SAR compliance.
    Records what was deleted, when, and why. Hashes the sorted list of
    deleted IDs (not PII content) for verifiability.

Also extends ``tbl_ai_assistants`` with:

  * ``retention_days`` — INT default 90, capped 400 (at INSERT/UPDATE).
    How long to keep messages for this assistant before ``retention_cleanup``
    deletes them. Per-assistant override of org default.

Revision ID: 0208_janitor_and_gdpr_log
Revises:     0207_add_ai_asst_leadsrc
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0208_janitor_and_gdpr_log"
down_revision: str | None = "0207_add_ai_asst_leadsrc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # tbl_janitor_heartbeats — global (no org_id). One row per beat task.
    # Used by health endpoint + monitoring to check if tasks are still
    # running. Simple upsert-on-write pattern.
    op.create_table(
        "tbl_janitor_heartbeats",
        sa.Column("name", sa.String(120), primary_key=True, nullable=False),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_run_status", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    # tbl_gdpr_deletion_log — org-scoped audit trail. Records what was
    # deleted (entity type + count), when, and reason. Hashes the sorted
    # list of deleted IDs for verifiability without storing PII.
    op.create_table(
        "tbl_gdpr_deletion_log",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(120), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=False),
        sa.Column("id_hash_sha256", sa.String(64), nullable=True),
        sa.Column("deletion_reason", sa.String(255), nullable=False),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["tbl_organizations.id"], ondelete="CASCADE"),
    )

    # Index on org_id + deleted_at for efficient time-windowed queries
    # (analytics, audit).
    op.create_index(
        "ix_gdpr_deletion_log_org_deleted",
        "tbl_gdpr_deletion_log",
        ["org_id", "deleted_at"],
    )

    # retention_days on tbl_ai_assistants: per-assistant override of
    # org-level retention policy. Nullable so legacy rows survive. Default 90.
    # Capped to 400 at write time by schema validator.
    op.add_column(
        "tbl_ai_assistants",
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("90"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_ai_assistants", "retention_days")
    op.drop_index("ix_gdpr_deletion_log_org_deleted", table_name="tbl_gdpr_deletion_log")
    op.drop_table("tbl_gdpr_deletion_log")
    op.drop_table("tbl_janitor_heartbeats")
