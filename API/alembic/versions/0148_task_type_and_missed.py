"""task followup_type column + missed task_status enum value

Step 1 of the ``tasks/dashboard-updates/`` track. Two additive
changes, both on ``tbl_tasks``:

1. New Postgres enum ``task_followup_type`` — ``call · whatsapp ·
   email · document · meeting · other`` — plus a new nullable
   ``followup_type`` column on ``tbl_tasks`` + a partial index on the
   dashboard widget's hot query shape.
2. New value ``missed`` added to the existing ``task_status`` enum so
   the widget can render + count follow-ups the rep explicitly closed
   without completing (or that the nightly grooming job auto-closed).

Both are non-destructive: existing task rows keep their current
``status`` / no ``followup_type`` value, and the widget treats
``NULL`` followup_type as "Other" in display.

Downgrade drops the followup_type index + column + enum cleanly.
Rebuilding the ``task_status`` enum without ``missed`` requires the
standard clone/cast/rename dance (Postgres has no ``DROP VALUE``);
any row currently at ``missed`` is flipped to ``open`` first so the
cast doesn't fail.

Revision ID: 0148_task_followup_type_and_missed_status
Revises: 0147_google_calendar_tokens
Create Date: 2026-07-01 11:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0148_task_type_and_missed"
down_revision: Union[str, None] = "0147_google_calendar_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FOLLOWUP_TYPES = ("call", "whatsapp", "email", "document", "meeting", "other")


def upgrade() -> None:
    # --- 1. task_followup_type enum ----------------------------------------
    postgresql.ENUM(
        *_FOLLOWUP_TYPES,
        name="task_followup_type",
        create_type=True,
    ).create(op.get_bind(), checkfirst=True)

    # --- 2. tbl_tasks.followup_type nullable column ------------------------
    op.add_column(
        "tbl_tasks",
        sa.Column(
            "followup_type",
            postgresql.ENUM(
                *_FOLLOWUP_TYPES,
                name="task_followup_type",
                create_type=False,
            ),
            nullable=True,
        ),
    )

    # --- 3. Partial index on the dashboard widget's hot query shape -------
    # (org_id, due_at, followup_type) WHERE status = 'open' — covers
    # "today's open follow-ups for this org, ordered by due_at, filtered
    # by type".
    op.create_index(
        "ix_tbl_tasks_org_due_type_pending",
        "tbl_tasks",
        ["org_id", "due_at", "followup_type"],
        postgresql_where=sa.text("status = 'open'"),
    )

    # --- 4. Add `missed` to task_status enum ------------------------------
    # ALTER TYPE ... ADD VALUE runs inside transactions on PG 12+.
    # IF NOT EXISTS keeps the migration idempotent if partially applied.
    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'missed'")


def downgrade() -> None:
    # --- 1. Drop the followup_type index + column + enum -----------------
    op.drop_index("ix_tbl_tasks_org_due_type_pending", table_name="tbl_tasks")
    op.drop_column("tbl_tasks", "followup_type")
    postgresql.ENUM(name="task_followup_type").drop(
        op.get_bind(), checkfirst=True
    )

    # --- 2. Rebuild task_status without `missed` --------------------------
    # Postgres has no DROP VALUE: clone the enum without `missed`, cast
    # the column to the clone, drop the old type, rename. Flip any rows
    # currently at `missed` to `open` first so the CAST doesn't fail.
    op.execute("UPDATE tbl_tasks SET status = 'open' WHERE status = 'missed'")
    op.execute(
        "CREATE TYPE task_status_old AS ENUM ('open', 'done', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE tbl_tasks "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE task_status_old "
        "USING status::text::task_status_old, "
        "ALTER COLUMN status SET DEFAULT 'open'"
    )
    op.execute("DROP TYPE task_status")
    op.execute("ALTER TYPE task_status_old RENAME TO task_status")
