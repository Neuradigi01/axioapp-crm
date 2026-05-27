"""activities: add 'reschedule' to activity_type ENUM

The appointments reschedule flow (Step 3 of `update-appointments-page`)
writes a dedicated audit activity for every time-shift so the
entity's timeline shows *"Asha's appointment was rescheduled from X
to Y."* — distinct from a generic `note` so the FE can render with a
calendar-clock icon and filter timelines by event type.

Same pattern as `0053_activity_type_reassign` and
`0057_activity_type_convert`. Wrapped in an `autocommit_block`
because `ALTER TYPE ... ADD VALUE` cannot run inside a transaction.

`IF NOT EXISTS` (PG 9.6+) makes the upgrade idempotent. Downgrade is
a no-op — Postgres can't drop an enum value safely (would require
recreating the type + swapping every reference). Existing rows
remain valid post-downgrade; the Python `ActivityType.reschedule`
member just stops being produced by app code.

Revision ID: 0059_activity_type_reschedule
Revises: 0058_appointments_last_activity
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0059_activity_type_reschedule"
down_revision: Union[str, None] = "0058_appointments_last_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'reschedule'"
        )


def downgrade() -> None:
    pass
