"""contact_imports — audit trail for XLSX/CSV bulk contact uploads
(Step 3.5.10).

One row per upload job. The flow is short — upload → dry-run → commit —
and runs synchronously in v1 (file-size cap = 10K rows, well within
inline-processing budget). A future step can add Celery if the size
cap rises.

State enum:
  uploaded   ── file parsed, headers detected, no rows inserted
  dry_run    ── operator confirmed mapping, dry-run counts cached
  committed  ── rows inserted; optionally a static group created
  failed     ── catastrophic failure (file unreadable, etc.)

`error_log` is a JSONB array of per-row errors:
  [{"row": 23, "reason": "phone too short", "raw": {"name": "X", ...}}, ...]

`created_group_id` is set when the operator opted to bundle the
import into a static contact group (Step 3.5.7 reuses the same table).
ON DELETE SET NULL on the FK keeps the audit row queryable if the
group is later deleted.

Tenant-scoped + RLS via `apply_rls("contact_imports")`.

Revision ID: 0067_contact_imports
Revises: 0066_contact_groups
Create Date: 2026-05-29 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0067_contact_imports"
down_revision: Union[str, None] = "0066_contact_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("uploaded", "dry_run", "committed", "failed")


def upgrade() -> None:
    # Idempotent CREATE TYPE — mirrors the DO-block pattern used by
    # `0048_integrations.py`. Survives a partial-prior-run scenario
    # (e.g. container auto-restart that created the type but rolled
    # back before the table).
    values = ", ".join(repr(v) for v in _STATUS_VALUES)
    op.execute(
        f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'contact_import_status'
    ) THEN
        CREATE TYPE contact_import_status AS ENUM ({values});
    END IF;
END
$$;
"""
    )

    op.create_table(
        "contact_imports",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("uploaded_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "error_log",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "suggested_mapping",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "applied_mapping",
            JSONB(),
            nullable=True,
        ),
        sa.Column(
            "headers",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_group_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            PgEnum(
                *_STATUS_VALUES,
                name="contact_import_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_group_id"],
            ["contact_groups.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contact_imports_org_status",
        "contact_imports",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_contact_imports_org_created_at",
        "contact_imports",
        ["org_id", "created_at"],
    )

    apply_rls("contact_imports")


def downgrade() -> None:
    drop_rls("contact_imports")
    op.drop_index(
        "ix_contact_imports_org_created_at", table_name="contact_imports"
    )
    op.drop_index(
        "ix_contact_imports_org_status", table_name="contact_imports"
    )
    op.drop_table("contact_imports")
    op.execute("DROP TYPE IF EXISTS contact_import_status")
