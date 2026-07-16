"""campaign_email_tracking — Email tracking timestamps + status enum

Extends ``tbl_campaign_messages`` with Email-specific tracking timestamps
and grows the shared ``campaign_message_status`` enum with ``opened`` +
``clicked`` values so dispatch (Campaigns v1 Step 05) can flip rows
through the full Email lifecycle:

  ``queued → sent → delivered → opened → clicked → done``
  ``queued → sent → failed`` (bounce / opt-out / provider error)

Columns added:

  * ``opened_at``      — first pixel hit. Set-once + idempotent.
  * ``first_click_at`` — first tracked link click. Set-once.
  * ``bounced_at``     — timestamp of the bounce classifier's flip.
  * ``bounce_type``    — ``hard`` / ``soft`` / ``spam_complaint`` /
    ``unsubscribe`` from :class:`EmailBounce`.
  * ``unsubscribed_at``— set when the contact unsubscribed via the
    campaign footer link (Step 06 populates it — column lands now to
    avoid a second migration).

Enum values ``opened`` + ``clicked`` are added via ``ALTER TYPE ADD
VALUE`` which Postgres requires be committed outside a transaction —
Alembic honours this by default when the migration runs standalone.

No indexes yet: aggregations count() over the small per-campaign row
set which is already covered by ``ix_campaign_messages_campaign_status``.

Revision ID: 0153_email_tracking
Revises: 0152_email_body_html
Create Date: 2026-07-16 00:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0153_email_tracking"
down_revision: Union[str, None] = "0152_email_body_html"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum extension — Postgres 12+ accepts ALTER TYPE ADD VALUE inside
    # transactions when IF NOT EXISTS is supplied.
    op.execute("ALTER TYPE campaign_message_status ADD VALUE IF NOT EXISTS 'opened'")
    op.execute("ALTER TYPE campaign_message_status ADD VALUE IF NOT EXISTS 'clicked'")

    # tbl_campaign_messages tracking columns.
    op.add_column(
        "tbl_campaign_messages",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_campaign_messages",
        sa.Column("first_click_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_campaign_messages",
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tbl_campaign_messages",
        sa.Column("bounce_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tbl_campaign_messages",
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_campaign_messages", "unsubscribed_at")
    op.drop_column("tbl_campaign_messages", "bounce_type")
    op.drop_column("tbl_campaign_messages", "bounced_at")
    op.drop_column("tbl_campaign_messages", "first_click_at")
    op.drop_column("tbl_campaign_messages", "opened_at")
    # Enum values dropped by rebuilding the type — omitted for
    # downgrade because Postgres doesn't support ALTER TYPE DROP VALUE
    # and the values are harmless if never used.
