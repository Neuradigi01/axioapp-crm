"""leads: last_activity_at + lost_reason picklist

Additive columns on `leads` to power the cross-CRM upgrade:

  - `last_activity_at` — denormalised "newest activity timestamp",
    bumped by the activities-service hook. Same pattern as contacts.
  - `lost_reason` — short picklist (price / timing / competitor /
    no_response / other). Required when the lead's pipeline stage
    flips to `is_lost=true` (enforced in the service layer).
  - `lost_reason_other` — free text when `lost_reason='other'`.

Index for the default sort ('newest activity first', nulls last) and
a CHECK constraint pinning `lost_reason` to the picklist values so
malformed values can't slip in via raw SQL.

`leads.status` is unchanged — the existing `active / won / lost` enum
plus the pipeline-stage-driven auto-sync is the canonical workflow.
We do NOT introduce a parallel state machine here; the picklist +
required-on-lost validation cover the only new requirement.

Revision ID: 0054_leads_last_act_lost_reason
Revises: 0053_activity_type_reassign
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0054_leads_last_act_lost_reason"
down_revision: Union[str, None] = "0053_activity_type_reassign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOST_REASON_CHECK = (
    "lost_reason IS NULL OR lost_reason IN "
    "('price','timing','competitor','no_response','other')"
)


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("lost_reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("lost_reason_other", sa.String(length=255), nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_leads_org_last_activity_desc "
        "ON leads (org_id, last_activity_at DESC NULLS LAST)"
    )

    op.create_check_constraint(
        "ck_leads_lost_reason_picklist", "leads", _LOST_REASON_CHECK
    )

    # Idempotent backfill from activities (mirrors contacts 0052).
    op.execute(
        """
        UPDATE leads
           SET last_activity_at = sub.max_ts
          FROM (
            SELECT entity_id, MAX(created_at) AS max_ts
              FROM activities
             WHERE entity_type = 'lead'
             GROUP BY entity_id
          ) sub
         WHERE leads.id = sub.entity_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_leads_lost_reason_picklist", "leads", type_="check")
    op.execute("DROP INDEX IF EXISTS ix_leads_org_last_activity_desc")
    op.drop_column("leads", "lost_reason_other")
    op.drop_column("leads", "lost_reason")
    op.drop_column("leads", "last_activity_at")
