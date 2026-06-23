"""tbl_messages — internal notes + @mentions
(whatsapp-platform-upgrade Step 13).

Two columns on the existing `tbl_messages` row:

  * ``is_internal BOOL NOT NULL DEFAULT FALSE`` — discriminator that
    flips the bubble to yellow styling on the frontend AND keeps the
    row out of any channel adapter `send()` call (notes never reach
    the customer). Existing inbound/outbound rows backfill to FALSE.

  * ``mentioned_user_ids UUID[] NOT NULL DEFAULT '{}'`` — list of
    org users the note's author tagged with ``@name``. The notes
    service fans out one notification per id on insert. Empty
    array for non-note rows.

No new index — the read path filters by `conversation_id` which
already has the ``ix_messages_conversation_created`` index; the
extra column projection costs nothing.

Chains after ``0098_phone_health_events``.

Revision ID: 0099_conv_internal_notes
Revises: 0098_phone_health_events
Create Date: 2026-06-22 00:07:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0099_conv_internal_notes"
down_revision: Union[str, None] = "0098_phone_health_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_messages",
        sa.Column(
            "is_internal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_messages",
        sa.Column(
            "mentioned_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_messages", "mentioned_user_ids")
    op.drop_column("tbl_messages", "is_internal")
