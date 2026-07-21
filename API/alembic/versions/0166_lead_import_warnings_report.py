"""Per-import warnings report file path.

Adds a nullable ``warnings_report_path`` column to
``tbl_lead_imports``. The bulk-import processor writes a sibling
``warnings.csv`` when a row's ``lead.pipeline_stage`` value doesn't
match any real stage — the row still lands as a lead (falling back
to the pipeline's first stage) and the substitution is stamped both
as a timeline note on the created lead AND as a row in this CSV so
operators can bulk-triage the substitutions.

Same shape as ``error_report_path`` (0041) and
``skipped_report_path`` (0165) — nullable, populated only when the
run produced at least one warning.

Revision ID: 0166_lead_import_warnings_report
Revises:     0165_lead_import_skipped_report
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0166_lead_import_warnings_report"
down_revision: str | None = "0165_lead_import_skipped_report"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_lead_imports",
        sa.Column("warnings_report_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_lead_imports", "warnings_report_path")
