"""campaigns + campaign_messages

Two tenant-scoped, RLS-on tables + two new ENUMs (`campaign_status`,
`campaign_message_status`). Reuses the existing `conversation_channel`
ENUM (from 0018) so the engine and the campaigns module are channel-
identical at the DB level.

Indexes:
  - campaigns(org_id, status)              for the inbox-list filter
  - campaigns(org_id, schedule_at)         for the upcoming-schedule poll
  - campaign_messages(campaign_id, status) for stats group-bys
  - campaign_messages UNIQUE(campaign_id, contact_id) — idempotency

Revision ID: 0021_campaigns
Revises: 0020_reviews
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0021_campaigns"
down_revision: Union[str, None] = "0020_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAMPAIGN_STATUS_VALUES = ("draft", "scheduled", "running", "done", "failed")
_MESSAGE_STATUS_VALUES = ("queued", "sent", "delivered", "read", "failed")


def upgrade() -> None:
    campaign_status_enum = postgresql.ENUM(
        *_CAMPAIGN_STATUS_VALUES, name="campaign_status", create_type=False
    )
    message_status_enum = postgresql.ENUM(
        *_MESSAGE_STATUS_VALUES,
        name="campaign_message_status",
        create_type=False,
    )
    # Reuse the existing ENUM created by 0018 — bind without create.
    channel_enum = postgresql.ENUM(name="conversation_channel", create_type=False)
    bind = op.get_bind()
    campaign_status_enum.create(bind, checkfirst=True)
    message_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "campaigns",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column(
            "audience_filter",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("template", sa.String(length=4096), nullable=False),
        sa.Column("schedule_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            campaign_status_enum,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
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
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaigns_org_status", "campaigns", ["org_id", "status"]
    )
    op.create_index(
        "ix_campaigns_org_schedule_at", "campaigns", ["org_id", "schedule_at"]
    )

    op.create_table(
        "campaign_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "channel_message_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "status",
            message_status_enum,
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaign_messages_campaign_status",
        "campaign_messages",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_campaign_messages_campaign_contact",
        "campaign_messages",
        ["campaign_id", "contact_id"],
        unique=True,
    )

    apply_rls("campaigns")
    apply_rls("campaign_messages")


def downgrade() -> None:
    drop_rls("campaign_messages")
    drop_rls("campaigns")
    op.drop_index(
        "ix_campaign_messages_campaign_contact",
        table_name="campaign_messages",
    )
    op.drop_index(
        "ix_campaign_messages_campaign_status",
        table_name="campaign_messages",
    )
    op.drop_table("campaign_messages")
    op.drop_index(
        "ix_campaigns_org_schedule_at", table_name="campaigns"
    )
    op.drop_index("ix_campaigns_org_status", table_name="campaigns")
    op.drop_table("campaigns")
    bind = op.get_bind()
    postgresql.ENUM(name="campaign_message_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="campaign_status").drop(bind, checkfirst=True)
    # Do NOT drop conversation_channel — owned by 0018.
