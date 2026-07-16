"""campaign_email_fields — sender identity + subject + preheader

Adds five nullable columns to ``tbl_campaigns`` so Email campaigns can
capture the sender mailbox, display name, reply-to, subject, and
inbox-preview text. Sits at the boundary between campaigns v1 Step 03
(this schema) and Step 05 (dispatch wiring); all columns are NULL for
existing WhatsApp rows, and the required-when-Email invariants are
enforced at the Pydantic schema layer, not by NOT NULL constraints
(so single-column INSERTs from admin scripts still work).

Columns on ``tbl_campaigns``:

  * ``email_account_id`` — FK -> ``tbl_email_accounts.id`` (ON DELETE
    RESTRICT). Populated only for Email campaigns; blocks accidental
    mailbox deletion while a scheduled/running Email campaign points
    at it.
  * ``sender_name`` — Display name in the From header ("Your Shop" in
    "Your Shop <sales@yourshop.com>"). 120 chars is the practical
    Gmail truncation point.
  * ``reply_to`` — Optional address override. 320 chars = RFC 5321
    local-part + '@' + domain hard limit.
  * ``subject`` — 998 chars = RFC 5322 line-length hard limit. Supports
    ``{{first_name}}``-style merge tags resolved at dispatch time.
  * ``preheader`` — Inbox preview snippet. ~90 chars is what Gmail /
    Apple Mail show; 200 gives slack for longer clients.

Indexes:

  * ``ix_campaigns_email_account_id`` — supports the "block delete
    while a campaign uses this mailbox" check that lives on the
    email-accounts side (Step 07). Cheap to add now.

No backfill: existing rows carry ``channel != 'email'`` (the dispatch
path is broken today for Email, so no live Email campaigns exist), so
NULL is the correct value everywhere. Down-migration drops the
columns + index — reversible.

Revision ID: 0151_campaign_email_fields
Revises: 0150_rp_property_tables
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0151_campaign_email_fields"
down_revision: Union[str, None] = "0150_rp_property_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "email_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_email_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column("sender_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column("reply_to", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column("subject", sa.String(length=998), nullable=True),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column("preheader", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_campaigns_email_account_id",
        "tbl_campaigns",
        ["email_account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_email_account_id", table_name="tbl_campaigns")
    op.drop_column("tbl_campaigns", "preheader")
    op.drop_column("tbl_campaigns", "subject")
    op.drop_column("tbl_campaigns", "reply_to")
    op.drop_column("tbl_campaigns", "sender_name")
    op.drop_column("tbl_campaigns", "email_account_id")
