"""additive columns on tbl_leads: Won capture + lifecycle stamps + currency.

Extends ``tbl_leads`` with six additive columns wired by the U-track
audit's F2 / F22 / F25 findings:

  * ``currency`` — ISO-4217 3-letter code (nullable — falls back to
    the org's default currency at render time). Wired to the org
    currency the frontend already surfaces via ``/users/me → org.currency``.
  * ``won_value`` — Numeric(14, 2), nullable. Actual closed-won amount
    (may differ from ``budget``). Populated by the move-stage endpoint
    when the destination stage is ``is_won=true``.
  * ``close_date`` — Date, nullable. Actual close date, stamped on
    move-to-Won.
  * ``won_reason`` — String(64), nullable. Optional free-text or
    picklist value for close reporting. Kept unconstrained by CHECK
    for now (unlike ``lost_reason``) to let orgs experiment before
    we lock a picklist.
  * ``won_at`` — timestamptz, nullable. Auto-stamped by the move-stage
    service on first entry into any ``is_won`` stage.
  * ``lost_at`` — timestamptz, nullable. Auto-stamped by the move-stage
    service on first entry into any ``is_lost`` stage.

Also adds a composite index ``(org_id, pipeline_stage, last_activity_at
DESC)`` — the kanban's hot query shape (per-column, sort-by-recent).
Migration 0070 already covers ``(org_id, lead_score DESC)`` and the
default ``(org_id, created_at DESC)`` composite; this closes the last
sort dimension the kanban issues without hitting a seq-scan on a busy
org.

All columns nullable + no default → non-destructive. Downgrade drops
each cleanly.

Revision ID: 0160_leads_won_lifecycle
Revises:     0159_contact_anonymised_at
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0160_leads_won_lifecycle"
down_revision: Union[str, None] = "0159_contact_anonymised_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_leads",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column("won_value", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column("close_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column("won_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_leads",
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Kanban sort composite. Partial on `status='active'` keeps the
    # index small (won/lost cards don't appear on the pipeline view).
    op.create_index(
        "ix_tbl_leads_org_stage_activity",
        "tbl_leads",
        ["org_id", "pipeline_stage", sa.text("last_activity_at DESC NULLS LAST")],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_leads_org_stage_activity", table_name="tbl_leads")
    op.drop_column("tbl_leads", "lost_at")
    op.drop_column("tbl_leads", "won_at")
    op.drop_column("tbl_leads", "won_reason")
    op.drop_column("tbl_leads", "close_date")
    op.drop_column("tbl_leads", "won_value")
    op.drop_column("tbl_leads", "currency")
