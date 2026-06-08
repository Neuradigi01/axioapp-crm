"""Add pending_checkout_session_id to subscriptions.

Persists the most recent Stripe Checkout Session ID created for the
org so Step 13's webhook can correlate the
`checkout.session.completed` / `checkout.session.expired` event back
to the local subscription row.

The column is cleared by the webhook handler on terminal events
(`completed` flips status forward; `expired` just nulls it out). A
non-null value means there's a hosted Checkout page in flight that
the operator can re-share with the user if they bookmarked or lost
the link.

Revision ID: 0078_subs_pending_checkout
Revises:     0077_subs_scheduled_changes
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0078_subs_pending_checkout"
down_revision: Union[str, None] = "0077_subs_scheduled_changes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "pending_checkout_session_id",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "pending_checkout_session_id")
