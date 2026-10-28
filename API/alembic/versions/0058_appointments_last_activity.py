"""appointments: last_activity_at

Adds the denormalised "newest activity timestamp" column to
`appointments`. Same pattern as contacts (0052), leads (0054), and
walk-ins (0055) — the activities-service insert hook updates it on
every activity write so the appointments worklist can sort by recency
and "stale" calendar entries float to the top.

Index for the default sort ("newest activity first", nulls last) and
an idempotent backfill from existing activities so rows that already
have history land with a populated value.

State-machine changes for `appointment_status` are NOT a schema change
— the ENUM already has scheduled/completed/cancelled/no_show. The
transition rules are enforced in the service layer in this same step.

Revision ID: 0058_appointments_last_activity
Revises: 0057_activity_type_convert
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0058_appointments_last_activity"
down_revision: Union[str, None] = "0057_activity_type_convert"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_appointments_org_last_activity_desc "
        "ON appointments (org_id, last_activity_at DESC NULLS LAST)"
    )

    # Idempotent backfill — mirrors contacts 0052 / leads 0054 / walkins 0055.
    op.execute(
        """
        UPDATE appointments
           SET last_activity_at = sub.max_ts
          FROM (
            SELECT entity_id, MAX(created_at) AS max_ts
              FROM activities
             WHERE entity_type = 'appointment'
             GROUP BY entity_id
          ) sub
         WHERE appointments.id = sub.entity_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_appointments_org_last_activity_desc")
    op.drop_column("appointments", "last_activity_at")
