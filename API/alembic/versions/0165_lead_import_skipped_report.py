"""Per-import skipped-rows report file path.

Adds a nullable ``skipped_report_path`` column to
``tbl_lead_imports`` so the bulk-import processor can persist a
sibling ``skipped.csv`` alongside the existing ``errors.csv``.

The result page uses the presence of this path to expose a
"Download duplicates report" button — parallel to the existing
"Download error report" surface — so operators can see which rows
collapsed onto which existing contact / open lead instead of
staring at an opaque `duplicates_skipped` counter.

Revision ID: 0165_lead_import_skipped_report
Revises:     0164_contact_import_opt_in
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0165_lead_import_skipped_report"
down_revision: str | None = "0164_contact_import_opt_in"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_lead_imports",
        sa.Column("skipped_report_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_lead_imports", "skipped_report_path")
