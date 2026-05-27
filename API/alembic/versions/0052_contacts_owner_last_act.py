"""contacts: assignee + last_activity_at

Two additive columns on `contacts` for the sales-worklist upgrade:

  - `assigned_to_id` — UUID FK to `users.id` (`ON DELETE SET NULL`).
    Catches `contacts` up to `leads` / `walk_ins` / `appointments`
    which already carry the column. Junior sales reps need a "my
    contacts" filter; admin / store-manager need bulk transfer.

  - `last_activity_at` — denormalised "newest activity timestamp"
    column. Bumped by the activities-service hook on every insert
    (see `core/activities/service.py`). Powers the "no activity in
    7 days" sort + filter on the contacts list. Activities table
    stays the authoritative log; this column is a fast-path read.

Two new indexes:

  - `ix_contacts_org_assigned_to (org_id, assigned_to_id)` — "my
    contacts" filter and bulk-reassign target lookups.

  - `ix_contacts_org_last_activity_desc (org_id, last_activity_at
    DESC NULLS LAST)` — drives the default sort on the list page.

Backfill: `UPDATE contacts SET last_activity_at = MAX(activities.
created_at WHERE entity_type='contact')`. Idempotent — re-running is
a no-op. `assigned_to_id` is left NULL on every existing row; reps
will be set via the bulk-reassign UI landing in Step 3.

Revision ID: 0052_contacts_owner_last_act
Revises: 0051_routing_and_dedup
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0052_contacts_owner_last_act"
down_revision: Union[str, None] = "0051_routing_and_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "assigned_to_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_contacts_org_assigned_to",
        "contacts",
        ["org_id", "assigned_to_id"],
    )
    # NULLS LAST in the index so the default DESC sort on the list
    # page puts never-touched contacts at the bottom without a
    # post-sort coalesce.
    op.execute(
        "CREATE INDEX ix_contacts_org_last_activity_desc "
        "ON contacts (org_id, last_activity_at DESC NULLS LAST)"
    )

    # Backfill last_activity_at from the activities table.
    # Idempotent: re-running picks the same MAX(created_at) per row.
    op.execute(
        """
        UPDATE contacts
           SET last_activity_at = sub.max_ts
          FROM (
            SELECT entity_id, MAX(created_at) AS max_ts
              FROM activities
             WHERE entity_type = 'contact'
             GROUP BY entity_id
          ) sub
         WHERE contacts.id = sub.entity_id
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_org_last_activity_desc")
    op.drop_index("ix_contacts_org_assigned_to", table_name="contacts")
    op.drop_column("contacts", "last_activity_at")
    op.drop_column("contacts", "assigned_to_id")
