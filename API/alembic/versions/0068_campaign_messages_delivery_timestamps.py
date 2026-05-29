"""campaign_messages: delivered_at + read_at — Meta delivery tracking
(Step 3.5.12).

The Step 3.5.12 webhook receiver consumes Meta's `statuses[]` array
and stamps these columns when WhatsApp reports the lifecycle events:

  sent       → existing `sent_at` is stamped by the dispatch path
  delivered  → `delivered_at = now()` + `status='delivered'`
  read       → `read_at = now()`      + `status='read'`
  failed     → `error` populated      + `status='failed'`

`campaign_message_status` already includes `delivered` and `read`
values (added in migration 0021); this step only adds the timestamp
columns. The Step 3.5.13 UI uses both — pill from `status` + tick
state derived from which timestamp is populated.

Revision ID: 0068_msg_delivery_ts
Revises: 0067_contact_imports
Create Date: 2026-05-29 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0068_msg_delivery_ts"
down_revision: Union[str, None] = "0067_contact_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_messages",
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "campaign_messages",
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("campaign_messages", "read_at")
    op.drop_column("campaign_messages", "delivered_at")
