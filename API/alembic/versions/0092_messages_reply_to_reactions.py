"""tbl_messages.reply_to_message_id + tbl_messages.reactions
(whatsapp-platform-upgrade Step 7).

Adds two columns to ``tbl_messages``:

* ``reply_to_message_id UUID NULL`` — self-referential FK that points to
  the message being quoted. ``ON DELETE SET NULL`` so deleting the
  original doesn't cascade-wipe its replies; the bubble renders
  "Original message deleted" when the FK is null but the row still
  represents a reply.
* ``reactions JSONB NOT NULL DEFAULT '[]'`` — append-only list of
  ``{user, emoji, ts}`` dicts for the message. WhatsApp limits one
  reaction per user per message; the service replaces the row in-place
  on each update so the list stays compact. Inbound reactions write to
  the *target* message's column, never the reaction event's own row.

Plus a partial index on ``(conversation_id, reply_to_message_id)``
constrained to ``WHERE reply_to_message_id IS NOT NULL`` — the
"show replies to this message" lookup hits a tiny B-tree instead of
scanning the full conversation.

Chains after ``0091_messages_interactive``.

Revision ID: 0092_messages_reply_to_reactions
Revises: 0091_messages_interactive
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0092_messages_reply_to_reactions"
down_revision: Union[str, None] = "0091_messages_interactive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_messages",
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_messages",
        sa.Column(
            "reactions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_messages_reply_to",
        "tbl_messages",
        ["conversation_id", "reply_to_message_id"],
        postgresql_where=sa.text("reply_to_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_reply_to", table_name="tbl_messages")
    op.drop_column("tbl_messages", "reactions")
    op.drop_column("tbl_messages", "reply_to_message_id")
