"""walk_ins: last_activity_at

Adds the denormalised "newest activity timestamp" column to `walk_ins`.
Same pattern as `contacts.last_activity_at` (migration 0052) and
`leads.last_activity_at` (migration 0054) — the activities-service
insert hook updates it on every activity write so the showroom
worklist can sort by recency.

Index for the default sort ("newest activity first", nulls last) and
an idempotent backfill from existing activities so rows that already
have history land with a populated value.

No state-machine changes here — the existing `walk_in_status` ENUM
keeps its values (browsing / interested / follow_up / converted /
left); transition rules are enforced in the service layer in this
same step.

Revision ID: 0055_walkins_last_activity
Revises: 0054_leads_last_act_lost_reason
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0055_walkins_last_activity"
down_revision: Union[str, None] = "0054_leads_last_act_lost_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "walk_ins",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_walkins_org_last_activity_desc "
        "ON walk_ins (org_id, last_activity_at DESC NULLS LAST)"
    )

    # Idempotent backfill — same SQL pattern as contacts 0052 / leads 0054.
    op.execute(
        """
        UPDATE walk_ins
           SET last_activity_at = sub.max_ts
          FROM (
            SELECT entity_id, MAX(created_at) AS max_ts
              FROM activities
             WHERE entity_type = 'walk_in'
             GROUP BY entity_id
          ) sub
         WHERE walk_ins.id = sub.entity_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_walkins_org_last_activity_desc")
    op.drop_column("walk_ins", "last_activity_at")
