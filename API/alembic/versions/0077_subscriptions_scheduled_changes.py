"""Add next_plan_code, next_billing_cycle, next_seats to subscriptions.

Used by the plan-change API (Step 8) to schedule downgrades and
cycle-down transitions that take effect at the next period boundary.
All three columns stay NULL until the first scheduled change lands on
a row; the lifecycle service (`apply_scheduled_change_if_due`) reads
them at the boundary, applies them to the live `plan_code` /
`billing_cycle` / `seats_purchased` columns, and clears them.

No backfill — existing rows naturally hold NULL in the new columns.

Revision ID: 0077_subs_scheduled_changes
Revises:     0076_subs_reminders_sent
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0077_subs_scheduled_changes"
down_revision: Union[str, None] = "0076_subs_reminders_sent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("next_plan_code", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("next_billing_cycle", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "subscriptions",
        sa.Column("next_seats", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "next_seats")
    op.drop_column("subscriptions", "next_billing_cycle")
    op.drop_column("subscriptions", "next_plan_code")
