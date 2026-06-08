"""stripe_webhook_events — idempotent webhook dedup ledger.

One row per Stripe event ID. The webhook router (sub-step 13.a) uses
`INSERT … ON CONFLICT DO NOTHING` against the primary key to dedup
replays; an existing row with `processed_at IS NOT NULL` short-
circuits the handler and returns 200 so Stripe stops retrying.

No `org_id` — the event may land before we have resolved which org
(`checkout.session.completed`'s metadata carries it; raw account-level
events do not). RLS is therefore off — the table is administrative,
not tenant-owned, and only the webhook code paths read or write it.

Revision ID: 0080_stripe_webhook_events
Revises:     0079_subscription_invoices
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0080_stripe_webhook_events"
down_revision: Union[str, None] = "0079_subscription_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_events",
        sa.Column("stripe_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("stripe_event_id"),
    )

    # Read pattern: "what events are still un-processed?" backed by a
    # partial index on `processed_at IS NULL`. Cheap maintenance + small
    # because most events complete.
    op.create_index(
        "ix_stripe_webhook_events_unprocessed",
        "stripe_webhook_events",
        ["received_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stripe_webhook_events_unprocessed",
        table_name="stripe_webhook_events",
    )
    op.drop_table("stripe_webhook_events")
