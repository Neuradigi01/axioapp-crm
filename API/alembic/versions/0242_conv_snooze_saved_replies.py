"""Conversations inbox: timed snooze, saved replies, badge-count index.

* ``tbl_conversations.snoozed_until`` — when set, the beat sweeper
  reopens the snoozed conversation at that instant. NULL keeps the
  existing "snoozed until the customer replies" behaviour.
* ``tbl_conversation_saved_replies`` — org-wide canned responses the
  composer can insert. Optional per-org unique ``shortcut``
  (case-insensitive). Tenant-scoped with RLS via ``apply_rls``.
* ``ix_conversations_org_status_assignee`` — backs the inbox's unread
  badge counts (status × assignee buckets).

Revision ID: 0242_conv_snooze_saved_replies
Revises:     0241_messages_text_trgm
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from src.app.shared.rls import apply_rls, drop_rls

revision: str = "0242_conv_snooze_saved_replies"
down_revision: str | None = "0241_messages_text_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_conversations",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_org_status_assignee",
        "tbl_conversations",
        ["org_id", "status", "assigned_to_id"],
    )

    op.create_table(
        "tbl_conversation_saved_replies",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("shortcut", sa.String(length=32), nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_tbl_conversation_saved_replies_org_id",
        "tbl_conversation_saved_replies",
        ["org_id"],
    )
    op.create_index(
        "ix_conv_saved_replies_org_title",
        "tbl_conversation_saved_replies",
        ["org_id", "title"],
    )
    op.create_index(
        "uq_conv_saved_replies_org_shortcut",
        "tbl_conversation_saved_replies",
        ["org_id", sa.text("lower(shortcut)")],
        unique=True,
        postgresql_where=sa.text("shortcut IS NOT NULL"),
    )
    apply_rls("tbl_conversation_saved_replies")


def downgrade() -> None:
    drop_rls("tbl_conversation_saved_replies")
    op.drop_index("uq_conv_saved_replies_org_shortcut", table_name="tbl_conversation_saved_replies")
    op.drop_index("ix_conv_saved_replies_org_title", table_name="tbl_conversation_saved_replies")
    op.drop_index(
        "ix_tbl_conversation_saved_replies_org_id", table_name="tbl_conversation_saved_replies"
    )
    op.drop_table("tbl_conversation_saved_replies")
    op.drop_index("ix_conversations_org_status_assignee", table_name="tbl_conversations")
    op.drop_column("tbl_conversations", "snoozed_until")
