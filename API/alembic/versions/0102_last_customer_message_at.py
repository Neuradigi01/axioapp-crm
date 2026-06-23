"""tbl_conversations.last_customer_message_at
(whatsapp-platform-upgrade Step 15).

Adds the timestamp the 24-hour WhatsApp session window pivots on.
Every inbound webhook from the customer updates this column atomically
with the message insert; the helper in `whatsapp_session.py` compares
it to ``now()`` to decide whether the agent can still free-text or
must send an approved template.

The migration backfills the column for existing conversations from
the most recent inbound ``tbl_messages.sent_at`` row per conversation
— rows with no inbound history land as NULL (the session helper
treats NULL as "out of session", which matches Meta's behaviour for
contacts that never initiated a conversation).

Chains after ``0101_backfill_tags_perm``.

Revision ID: 0102_last_cust_msg_at
Revises: 0101_backfill_tags_perm
Create Date: 2026-06-23 00:02:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0102_last_cust_msg_at"
down_revision: Union[str, None] = "0101_backfill_tags_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "last_customer_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Backfill from the latest inbound message timestamp per
    # conversation. `direction = 'in'` filters to customer-driven
    # messages; outbound + internal-note rows don't count toward the
    # session window. Uses correlated subquery for clarity over CTE
    # — both produce the same plan on Postgres 15+.
    op.execute(
        """
        UPDATE tbl_conversations c
        SET last_customer_message_at = (
            SELECT MAX(m.sent_at)
            FROM tbl_messages m
            WHERE m.conversation_id = c.id
              AND m.direction = 'in'
              AND m.sent_at IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_column("tbl_conversations", "last_customer_message_at")
