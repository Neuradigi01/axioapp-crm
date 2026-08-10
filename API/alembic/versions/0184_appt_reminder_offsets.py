"""Configurable appointment reminder offsets.

Adds ``tbl_org_settings.appointment_reminder_offsets_minutes`` — a JSONB
list of positive integers describing how many minutes BEFORE an
appointment's ``scheduled_at`` a reminder should fire. The Celery beat
task ``core.appointments.tasks.scan_for_reminders`` reads this per-org
list on each tick instead of the previously-hardcoded 24h + 1h offsets.

Default ``[1440, 60]`` preserves the pre-migration behaviour (reminder
24h + 1h before) for every existing org, so nothing observable changes
until an operator edits the value from the Settings page.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0184_appt_reminder_offsets"
down_revision: str | None = "0183_msg_wamid_uniq"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "appointment_reminder_offsets_minutes",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[1440, 60]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_org_settings", "appointment_reminder_offsets_minutes")
