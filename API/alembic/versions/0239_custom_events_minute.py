"""Date-triggered custom events — minute-of-hour fire time.

Adds ``schedule_minute_local`` to ``tbl_custom_events`` so a scheduled
event fires at an operator-picked ``HH:MM`` (5-minute steps) instead of
only on the hour. The sweep moves from hourly to every 5 minutes and
matches ``(schedule_hour_local, schedule_minute_local)`` against the
org's current local 5-minute slot.

Existing ``date_field`` events are backfilled to ``0`` so they keep
firing at the top of their configured hour. Manual events stay NULL
(mirrors ``schedule_hour_local``).

Revision ID: 0239_custom_events_minute
Revises:     0238_campaigns_archived_at
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0239_custom_events_minute"
down_revision: str | None = "0238_campaigns_archived_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_minute_local", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE tbl_custom_events SET schedule_minute_local = 0 WHERE schedule_type = 'date_field'"
    )
    op.create_check_constraint(
        "ck_custom_events_schedule_minute_range",
        "tbl_custom_events",
        "schedule_minute_local IS NULL OR "
        "(schedule_minute_local BETWEEN 0 AND 55 AND schedule_minute_local % 5 = 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_custom_events_schedule_minute_range", "tbl_custom_events", type_="check")
    op.drop_column("tbl_custom_events", "schedule_minute_local")
