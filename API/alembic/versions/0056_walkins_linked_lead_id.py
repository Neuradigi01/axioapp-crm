"""walk_ins: linked_lead_id (Walk-in → Lead conversion)

Adds a nullable FK from `walk_ins` to `leads` so a walk-in can be
"converted" — meaning a Lead row is spun up from the visitor's
contact + requirements, and the originating walk-in keeps a pointer
back to it. The pointer powers two things:

  1. The Convert modal refuses to re-convert an already-linked
     walk-in (returns 409 with the existing lead id so the FE can
     redirect to the lead).
  2. The walk-in list shows a "→ Lead" link badge on rows that have
     been converted, so reps see at a glance which visitors made it
     to the funnel.

`ON DELETE SET NULL` so deleting a lead doesn't cascade-delete the
walk-in history — the historical visit record is independently
useful for showroom analytics.

Revision ID: 0056_walkins_linked_lead_id
Revises: 0055_walkins_last_activity
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0056_walkins_linked_lead_id"
down_revision: Union[str, None] = "0055_walkins_last_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "walk_ins",
        sa.Column(
            "linked_lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_walkins_org_linked_lead",
        "walk_ins",
        ["org_id", "linked_lead_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_walkins_org_linked_lead", table_name="walk_ins")
    op.drop_column("walk_ins", "linked_lead_id")
