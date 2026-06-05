"""Add reminders_sent JSONB column to subscriptions.

Used by the trial-lifecycle Celery task (Step 6) to dedupe the
"trial ending in 3 days" reminder email. The column starts as `{}`
on every row; the lifecycle service flips
`reminders_sent['trial_ending_soon'] = true` once it has queued the
email. A second pass on the same day is a no-op.

JSONB instead of a separate `subscription_reminders` table because
the reminder taxonomy is tiny (we expect 1-3 keys for v1) and lives
1:1 with the subscription. Adding more reminders later only adds
keys, no schema migration.

Revision ID: 0076_subs_reminders_sent
Revises:     0075_usage_counters_table
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0076_subs_reminders_sent"
down_revision: Union[str, None] = "0075_usage_counters_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "reminders_sent",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "reminders_sent")
