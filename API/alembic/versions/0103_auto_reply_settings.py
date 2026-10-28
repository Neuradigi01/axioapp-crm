"""tbl_whatsapp_account_configs — auto-reply settings columns
(whatsapp-platform-upgrade Step 16).

Wires the Step-11 greeting / away message text + business hours to
the auto-reply pipeline that fires on inbound webhooks. Four new
columns:

  * ``greeting_enabled BOOL NOT NULL DEFAULT FALSE`` — operator toggle
    for the new-contact greeting auto-reply.
  * ``away_enabled BOOL NOT NULL DEFAULT FALSE`` — operator toggle for
    the out-of-business-hours auto-reply.
  * ``greeting_template_id UUID NULL`` — fallback approved template
    used when the contact is out of the 24-hour session window
    (free text won't be delivered then). FK to
    ``tbl_whatsapp_templates`` with ``ON DELETE SET NULL`` so a
    template deletion clears the reference but leaves the toggle
    intact (the operator gets a "select a new template" notice).
  * ``away_template_id UUID NULL`` — same role for the away path.

Greeting / away message text is already on the row (Step 11). This
migration only adds the enable flags + template fallback references.

Chains after ``0102_last_cust_msg_at``.

Revision ID: 0103_auto_reply_settings
Revises: 0102_last_cust_msg_at
Create Date: 2026-06-23 00:03:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0103_auto_reply_settings"
down_revision: Union[str, None] = "0102_last_cust_msg_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "greeting_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "away_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "greeting_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_templates.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "away_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_templates.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_whatsapp_account_configs", "away_template_id")
    op.drop_column("tbl_whatsapp_account_configs", "greeting_template_id")
    op.drop_column("tbl_whatsapp_account_configs", "away_enabled")
    op.drop_column("tbl_whatsapp_account_configs", "greeting_enabled")
