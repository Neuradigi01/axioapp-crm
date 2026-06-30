"""workflows cached counters

Step 19 of ``tasks/workflows/`` — adds 2 cached-counter columns to
``tbl_workflows`` so the list page can render per-row "running" +
"completed today" mini-stats without firing a per-row aggregate query.
A 5-minute Celery beat task (``refresh_workflow_cached_counters``)
recomputes both columns org-wide; the full analytics endpoint
(/workflows/{id}/analytics) queries live and ignores the cache.

Columns added:

  * ``cached_running_count``           int default 0
  * ``cached_completed_today_count``   int default 0

Reversible — downgrade drops both columns. No index needed; the list
page already paginates on ``updated_at`` and reads these as scalar
columns.

Revision ID: 0143_workflow_cached_counters
Revises: 0142_workflow_ab_columns
Create Date: 2026-06-30 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0143_workflow_cached_counters"
down_revision: Union[str, None] = "0142_workflow_ab_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "cached_running_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "tbl_workflows",
        sa.Column(
            "cached_completed_today_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_workflows", "cached_completed_today_count")
    op.drop_column("tbl_workflows", "cached_running_count")
