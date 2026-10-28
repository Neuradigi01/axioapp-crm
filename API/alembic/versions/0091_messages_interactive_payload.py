"""tbl_messages.interactive_payload — JSONB column for outbound Meta
interactive messages (whatsapp-platform-upgrade Step 6).

Stores the Meta-spec ``interactive`` envelope the operator built in the
composer's interactive-builder modal — reply buttons / CTA buttons /
list. Persisted as JSONB on the outbound message row so the inbox can
re-render button labels in the thread bubble and the audit trail
shows exactly what the operator sent.

Nullable because the column applies only to outbound interactive sends;
text / template / media messages leave it NULL. No index needed — the
column is read whenever a message row is rendered, but only via the
existing ``(conversation_id, created_at)`` retrieval pattern.

Chains after ``0090_meta_data_deletion``.

Revision ID: 0091_messages_interactive_payload
Revises: 0090_meta_data_deletion
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0091_messages_interactive"
down_revision: Union[str, None] = "0090_meta_data_deletion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_messages",
        sa.Column(
            "interactive_payload",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_messages", "interactive_payload")
