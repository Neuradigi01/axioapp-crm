"""tbl_whatsapp_account_configs — business profile columns
(whatsapp-platform-upgrade Step 11).

Extends the existing per-org WhatsApp config row with the editable
Meta Business profile fields plus two Core-CRM-only fields that
Step 16 (Welcome / out-of-hours auto-reply) will read:

Profile (mirrors Meta's `whatsapp_business_profile` shape):
  * profile_about        VARCHAR(139)   — short tagline
  * profile_description  VARCHAR(512)   — long description
  * profile_address      VARCHAR(256)
  * profile_email        VARCHAR(128)
  * profile_websites     JSONB          — list of up to 2 URLs
  * profile_vertical     VARCHAR(64)    — Meta-published vertical
  * profile_picture_url  VARCHAR(512)   — public URL set by upload
  * profile_last_synced_at TIMESTAMPTZ  — last Meta refresh

Automation hooks (storage only — Step 16 wires behaviour):
  * business_hours JSONB
       [{day: 0..6, intervals: [{open: "HH:MM", close: "HH:MM"}]}]
       Day 0 = Monday, ISO-style. Closed days omit intervals.
  * greeting_message TEXT NULL
  * away_message    TEXT NULL

All columns nullable — the Step 11 form treats missing values as
"never edited" and the Meta GET on first open populates the defaults.

Chains after ``0095_backfill_wa_perms``.

Revision ID: 0096_wa_business_profile
Revises: 0095_backfill_wa_perms
Create Date: 2026-06-22 00:04:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0096_wa_business_profile"
down_revision: Union[str, None] = "0095_backfill_wa_perms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_about", sa.String(length=139), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_description", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_address", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_email", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_websites", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_vertical", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("profile_picture_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "profile_last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("business_hours", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("greeting_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("away_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_whatsapp_account_configs", "away_message")
    op.drop_column("tbl_whatsapp_account_configs", "greeting_message")
    op.drop_column("tbl_whatsapp_account_configs", "business_hours")
    op.drop_column("tbl_whatsapp_account_configs", "profile_last_synced_at")
    op.drop_column("tbl_whatsapp_account_configs", "profile_picture_url")
    op.drop_column("tbl_whatsapp_account_configs", "profile_vertical")
    op.drop_column("tbl_whatsapp_account_configs", "profile_websites")
    op.drop_column("tbl_whatsapp_account_configs", "profile_email")
    op.drop_column("tbl_whatsapp_account_configs", "profile_address")
    op.drop_column("tbl_whatsapp_account_configs", "profile_description")
    op.drop_column("tbl_whatsapp_account_configs", "profile_about")
