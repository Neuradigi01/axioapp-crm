"""conversations + messages

Two-table migration for the channel-agnostic conversations engine plus
three Postgres ENUMs (channel / status / direction). RLS-on; the hot
inbox-list index is `(org_id, last_message_at DESC)` so the default
sort hits the index; `(channel, external_id)` is the lookup the
webhook intake uses to find an existing conversation.

Revision ID: 0018_conversations
Revises: 0017_staff_sessions
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0018_conversations"
down_revision: Union[str, None] = "0017_staff_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHANNEL_VALUES = ("whatsapp", "instagram", "facebook", "web", "sms", "email")
_STATUS_VALUES = ("open", "snoozed", "closed")
_DIRECTION_VALUES = ("in", "out")


def upgrade() -> None:
    channel_enum = postgresql.ENUM(
        *_CHANNEL_VALUES, name="conversation_channel", create_type=False
    )
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES, name="conversation_status", create_type=False
    )
    direction_enum = postgresql.ENUM(
        *_DIRECTION_VALUES, name="message_direction", create_type=False
    )
    bind = op.get_bind()
    channel_enum.create(bind, checkfirst=True)
    status_enum.create(bind, checkfirst=True)
    direction_enum.create(bind, checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "ai_handling",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "last_message_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "unread_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_org_last_message",
        "conversations",
        ["org_id", "last_message_at"],
    )
    op.create_index(
        "ix_conversations_channel_external_id",
        "conversations",
        ["channel", "external_id"],
    )

    op.create_table(
        "messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("sender_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "channel_message_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivered_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )

    apply_rls("conversations")
    apply_rls("messages")


def downgrade() -> None:
    drop_rls("messages")
    drop_rls("conversations")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        "ix_conversations_channel_external_id", table_name="conversations"
    )
    op.drop_index(
        "ix_conversations_org_last_message", table_name="conversations"
    )
    op.drop_table("conversations")
    bind = op.get_bind()
    postgresql.ENUM(name="message_direction").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="conversation_channel").drop(bind, checkfirst=True)
