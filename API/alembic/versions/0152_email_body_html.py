"""template_and_campaign_body_html — HTML body support for Email

Adds ``body_html`` + ``body_text_fallback_auto`` to
``tbl_message_templates`` (and ``body_html`` to
``tbl_message_template_versions`` for immutable version snapshots),
plus a ``body_html`` column on ``tbl_campaigns`` for inline authored
Email bodies that don't reference a template.

All columns are nullable except ``body_text_fallback_auto`` (BOOLEAN
NOT NULL DEFAULT ``true``) — dispatch (Campaigns v1 Step 05) reads the
flag to know whether it should auto-derive a plain-text fallback from
the HTML when ``body_text`` is empty. Existing rows carry the default,
so no per-row backfill is needed.

The service layer (:mod:`core.templates.sanitizer`) enforces XSS
scrubbing before every write, so storing raw HTML is safe at the DB
level; the CHECK constraints would be redundant.

Revision ID: 0152_email_body_html
Revises: 0151_campaign_email_fields
Create Date: 2026-07-16 00:05:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0152_email_body_html"
down_revision: Union[str, None] = "0151_campaign_email_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tbl_message_templates ------------------------------------------
    op.add_column(
        "tbl_message_templates",
        sa.Column("body_html", sa.Text(), nullable=True),
    )
    op.add_column(
        "tbl_message_templates",
        sa.Column(
            "body_text_fallback_auto",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # tbl_message_template_versions ----------------------------------
    op.add_column(
        "tbl_message_template_versions",
        sa.Column("body_html", sa.Text(), nullable=True),
    )

    # tbl_campaigns --------------------------------------------------
    op.add_column(
        "tbl_campaigns",
        sa.Column("body_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_campaigns", "body_html")
    op.drop_column("tbl_message_template_versions", "body_html")
    op.drop_column("tbl_message_templates", "body_text_fallback_auto")
    op.drop_column("tbl_message_templates", "body_html")
