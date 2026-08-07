"""Partial unique index on ``tbl_messages(conversation_id, channel_message_id)``.

WhatsApp Cloud API retries webhook deliveries for up to 7 days on any
non-2xx response. Without a uniqueness guarantee, a redelivery of the
same wamid can insert a duplicate ``Message`` row. This adds a partial
unique index (partial because outbound rows and non-WhatsApp channels
have ``channel_message_id IS NULL``) scoped per-conversation so the DB
enforces at-most-once persistence per inbound message.

Any pre-existing duplicates are cleaned up first — the earliest row
(min ``created_at``) is retained; later duplicates are removed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0183_msg_wamid_uniq"
down_revision: str | None = "0182_workflow_schedules"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM tbl_messages a
        USING tbl_messages b
        WHERE a.conversation_id = b.conversation_id
          AND a.channel_message_id = b.channel_message_id
          AND a.channel_message_id IS NOT NULL
          AND (a.created_at > b.created_at
               OR (a.created_at = b.created_at AND a.id > b.id))
        """
    )
    op.create_index(
        "uq_messages_conv_wamid",
        "tbl_messages",
        ["conversation_id", "channel_message_id"],
        unique=True,
        postgresql_where=sa.text("channel_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_messages_conv_wamid",
        table_name="tbl_messages",
        postgresql_where=sa.text("channel_message_id IS NOT NULL"),
    )
