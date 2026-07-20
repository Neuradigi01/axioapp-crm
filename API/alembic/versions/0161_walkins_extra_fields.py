"""additive fields on tbl_walk_ins + tbl_leads.source_walk_in_id
(walk-ins review W6/W8/W9/W11).

Extends ``tbl_walk_ins`` with three optional fields called out by the
Phase 1 shape audit + one reverse-link column on ``tbl_leads``:

  * ``party_size`` — SMALLINT NULL. Group-visit tracking; a family of
    four counts as one walk-in row but rolls up as 4 visitors in
    footfall reports.
  * ``wait_started_at`` — TIMESTAMPTZ NULL. Queue-arrival timestamp
    (before rep engagement). ``time_in`` becomes "engaged at";
    (time_in − wait_started_at) = wait time. Optional — orgs that
    don't track a queue leave it NULL and get today's UX unchanged.
  * ``expected_return_date`` — DATE NULL. "Customer said they'd come
    back Saturday." Feeds retention / return-visit reports.
  * ``tbl_leads.source_walk_in_id`` — UUID NULL, FK to
    ``tbl_walk_ins.id`` with ondelete=SET NULL. Populated by
    ``convert_walk_in_to_lead`` so leads carry a reverse-link to
    their originating showroom visit. The lead detail can then render
    "originated from walk-in on X" and analytics can attribute won
    revenue back to walk-in cohorts.

All columns nullable + no default → non-destructive on existing rows.
Downgrade drops each cleanly.

Revision ID: 0161_walkins_extra_fields
Revises:     0160_leads_won_lifecycle
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0161_walkins_extra_fields"
down_revision: Union[str, None] = "0160_leads_won_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_walk_ins",
        sa.Column("party_size", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "tbl_walk_ins",
        sa.Column("wait_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_walk_ins",
        sa.Column("expected_return_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column(
            "source_walk_in_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_walk_ins.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Filtered index — "which leads came from a walk-in" is a fast
    # attribution lookup; the vast majority of leads have
    # source_walk_in_id IS NULL, so partial index keeps size small.
    op.create_index(
        "ix_tbl_leads_source_walk_in",
        "tbl_leads",
        ["source_walk_in_id"],
        postgresql_where=sa.text("source_walk_in_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_leads_source_walk_in", table_name="tbl_leads")
    op.drop_column("tbl_leads", "source_walk_in_id")
    op.drop_column("tbl_walk_ins", "expected_return_date")
    op.drop_column("tbl_walk_ins", "wait_started_at")
    op.drop_column("tbl_walk_ins", "party_size")
