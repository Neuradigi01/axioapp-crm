"""Per-import skipped-rows and warnings reports for contacts.

Adds four nullable-ish columns to ``tbl_contact_imports`` so the
contact-import surface can split its persisted report data into
errors + skipped duplicates + warnings — matching the leads-import
surface's 3-CSV download pattern (errors.csv, skipped.csv,
warnings.csv). See ``0165_lead_import_skipped_report`` and
``0166_lead_import_warnings_report`` for the leads-side equivalents.

Contacts stores each report inline as JSONB (mirroring the existing
``error_log`` column) rather than a file-on-disk path — matches the
module's existing pattern and lets the CSV endpoints generate the
downloadable file on demand from the persisted rows.

Revision ID: 0172_contact_import_reports
Revises:     0171_audit_log_org_created_idx
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0172_contact_import_reports"
down_revision: str | None = "0171_audit_log_org_created_idx"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_contact_imports",
        sa.Column(
            "duplicate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "tbl_contact_imports",
        sa.Column(
            "duplicate_log",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "tbl_contact_imports",
        sa.Column(
            "warning_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "tbl_contact_imports",
        sa.Column(
            "warning_log",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_contact_imports", "warning_log")
    op.drop_column("tbl_contact_imports", "warning_count")
    op.drop_column("tbl_contact_imports", "duplicate_log")
    op.drop_column("tbl_contact_imports", "duplicate_count")
