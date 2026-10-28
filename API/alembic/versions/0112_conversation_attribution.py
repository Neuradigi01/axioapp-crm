"""Conversation acquisition / attribution columns
(whatsapp-platform-upgrade Step 24).

Captures Meta's ``referral`` block (and future QR / wa.me / form
referrers) on the conversation row itself. Single-touch: we record
the *first* source that produced the conversation; subsequent
inbound messages don't overwrite. Multi-touch attribution is a
future track per the step spec.

Columns (all nullable so existing rows stay valid):

  * ``acquisition_source`` — ENUM {organic / ad / qr / wa_me / form}.
    NULL for pre-existing conversations (treated as ``organic``).
  * ``acquisition_campaign_id`` — Meta Ads campaign id when source=ad;
    QR code id for source=qr; future expansion for other channels.
  * ``acquisition_ad_id`` — Meta Ads creative id when source=ad.
  * ``acquisition_landing_url`` — ``source_url`` from the referral or
    the landing page that produced the click.
  * ``acquisition_referral_payload`` — raw JSONB of Meta's
    ``referral`` block (forensics + future fields).

Chains after ``0111_block_list``.

Revision ID: 0112_conv_attribution
Revises: 0111_block_list
Create Date: 2026-06-24 05:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0112_conv_attribution"
down_revision: Union[str, None] = "0111_block_list"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SOURCE_VALUES = ("organic", "ad", "qr", "wa_me", "form")


def upgrade() -> None:
    source_enum = postgresql.ENUM(
        *_SOURCE_VALUES, name="conversation_acquisition_source"
    )
    source_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tbl_conversations",
        sa.Column(
            "acquisition_source",
            postgresql.ENUM(
                *_SOURCE_VALUES,
                name="conversation_acquisition_source",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column("acquisition_campaign_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column("acquisition_ad_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "acquisition_landing_url", sa.String(2048), nullable=True
        ),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "acquisition_referral_payload",
            postgresql.JSONB,
            nullable=True,
        ),
    )

    # Reporting hot-path: per-campaign roll-up. Partial index on rows
    # that actually carry a campaign id so the index stays small
    # (every other conversation has NULL here).
    op.create_index(
        "ix_conversations_org_campaign",
        "tbl_conversations",
        ["org_id", "acquisition_campaign_id"],
        postgresql_where=sa.text("acquisition_campaign_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_org_campaign", table_name="tbl_conversations"
    )
    op.drop_column("tbl_conversations", "acquisition_referral_payload")
    op.drop_column("tbl_conversations", "acquisition_landing_url")
    op.drop_column("tbl_conversations", "acquisition_ad_id")
    op.drop_column("tbl_conversations", "acquisition_campaign_id")
    op.drop_column("tbl_conversations", "acquisition_source")
    sa.Enum(name="conversation_acquisition_source").drop(
        op.get_bind(), checkfirst=True
    )
