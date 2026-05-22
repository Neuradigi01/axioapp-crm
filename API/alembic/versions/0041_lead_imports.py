"""lead_imports — bulk import job table for the leads-ingestion track.

One row per uploaded file. State machine:

  awaiting_mapping → mapping_committed → processing → completed
                                                    ↘ failed
  awaiting_mapping → cancelled
  mapping_committed → cancelled

Step 1 of the bulk-import track ships only the schema + the upload
endpoint, which creates rows in `awaiting_mapping`. The remaining
states are driven by Steps 2 + 3 (mapping-commit endpoint + Celery
processor).

`mapping`, `counts`, `error_report_path` are all NULL at this step —
they're populated by later steps. Indexed for the list endpoint's hot
read path: `(org_id, status, created_at DESC)`.

`uploaded_by` is a plain UUID, no FK to `users(id)`, per the
post-0037 convention documented in `0039_standard_field_overrides`
(the legacy `users` table is on soak; UUID columns join semantically
against `tbl_user_login.legacy_uuid` at the app layer).

Revision ID: 0041_lead_imports
Revises: 0040_lead_source
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0041_lead_imports"
down_revision: Union[str, None] = "0040_lead_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = (
    "awaiting_mapping",
    "mapping_committed",
    "processing",
    "completed",
    "failed",
    "cancelled",
)


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="lead_import_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "lead_imports",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        # No FK to users(id) — post-0037 convention.
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_platform", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("row_count_estimate", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'awaiting_mapping'"),
            nullable=False,
        ),
        sa.Column("mapping", JSONB, nullable=True),
        sa.Column("counts", JSONB, nullable=True),
        sa.Column("error_report_path", sa.Text(), nullable=True),
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
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_imports_org_status_created",
        "lead_imports",
        ["org_id", "status", sa.text("created_at DESC")],
    )

    apply_rls("lead_imports")


def downgrade() -> None:
    drop_rls("lead_imports")
    op.drop_index(
        "ix_lead_imports_org_status_created", table_name="lead_imports"
    )
    op.drop_table("lead_imports")
    postgresql.ENUM(name="lead_import_status").drop(
        op.get_bind(), checkfirst=True
    )
