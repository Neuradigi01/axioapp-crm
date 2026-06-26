"""conversations: add 'push' to conversation_channel ENUM

Step 13 of ``tasks/template-library`` introduces push notifications
as a first-class template channel. The conversations engine's
``conversation_channel`` PG enum gains a new value ``push`` so:

* The central templates table (``tbl_message_templates``) can store
  push templates without a CHECK constraint dance.
* The future push provider (Firebase Cloud Messaging / OneSignal /
  APNS) plugs in as a normal channel adapter via the registry.
* Inbox views that filter by channel pick up push automatically.

There is no migration for downstream tables today because the stub
adapter never writes a ``Conversation`` / ``Message`` row — push
sends are one-shot in this phase (no conversation surface). When a
real provider lands it'll persist outbound rows like every other
channel.

``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` is idempotent in PG 9.6+,
so re-running the migration is safe. Wrapped in an
``autocommit_block`` because the statement cannot run inside a
transaction (PG hard requirement).

Downgrade is a **no-op** — Postgres does not support
``ALTER TYPE ... DROP VALUE``. Removing the value would require
recreating the enum + swapping every column, which is high-risk for
no upside (zero rows reference it post-downgrade — push templates
are NEW in this step).

Revision ID: 0124_add_push_channel_enum
Revises: 0123_sms_dlt_templates
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0124_add_push_channel_enum"
down_revision: Union[str, None] = "0123_sms_dlt_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE conversation_channel ADD VALUE IF NOT EXISTS 'push'"
        )


def downgrade() -> None:
    # See module docstring — Postgres can't drop an enum value safely.
    # The Python ``ConversationChannel.push`` member will simply not be
    # produced by app code post-downgrade; the enum value remains
    # defined but unreachable from application code.
    pass
