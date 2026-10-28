"""tasks: last_activity_at

Adds the denormalised "newest activity timestamp" column to `tasks`.
Same pattern as contacts (0052), leads (0054), walk-ins (0055),
appointments (0058) — the activities-service insert hook keeps it
fresh, and the tasks-service write paths also bump it independently
because not every task update creates an activity row (a title edit
doesn't, for instance, but the user still expects "recent activity"
to surface it).

Index for the default sort ("newest activity first", nulls last) and
an idempotent backfill that picks the max of `updated_at` and any
matching `activities.created_at`. The tasks model has no `done_at`
column (status flips happen via the generic `updated_at` bump), so
the backfill stays simple.

Revision ID: 0060_tasks_last_activity
Revises: 0059_activity_type_reschedule
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0060_tasks_last_activity"
down_revision: Union[str, None] = "0059_activity_type_reschedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_tasks_org_last_activity_desc "
        "ON tasks (org_id, last_activity_at DESC NULLS LAST)"
    )

    # Idempotent backfill: pick the most recent of `updated_at` and
    # any logged activity. Same SQL shape as the prior entity
    # backfills (0052/0054/0055/0058); the GREATEST handles the join
    # subquery gracefully when there is no activity row (the subquery
    # returns NULL → GREATEST(updated_at, NULL) = updated_at).
    op.execute(
        """
        UPDATE tasks
           SET last_activity_at = GREATEST(
                 tasks.updated_at,
                 COALESCE(sub.max_ts, '-infinity'::timestamptz)
               )
          FROM (
            SELECT entity_id, MAX(created_at) AS max_ts
              FROM activities
             WHERE entity_type = 'task'
             GROUP BY entity_id
          ) sub
         WHERE tasks.id = sub.entity_id
        """
    )
    # Tasks that never had an activity row still need their column
    # populated so the column isn't all-NULL after the migration.
    op.execute(
        """
        UPDATE tasks
           SET last_activity_at = tasks.updated_at
         WHERE last_activity_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_org_last_activity_desc")
    op.drop_column("tasks", "last_activity_at")
