"""Cross-channel per-org partial unique index on ``tbl_messages``.

Existing schema has ``uq_messages_conv_wamid`` at
``(conversation_id, channel_message_id) WHERE channel_message_id IS
NOT NULL`` — that catches retries whose threading logic picks the
same conversation. A retry (or Mailgun replay) whose threading picks
a *different* conversation for the same delivery would slip through.

This migration adds ``uq_messages_org_channel_msgid`` at
``(org_id, channel_message_id) WHERE channel_message_id IS NOT NULL``
— per-org guarantee of at-most-once persistence for every provider
that sets a channel-side ID (Gmail sync, Microsoft sync, WhatsApp
webhook, Meta messaging, and the future Mailgun inbound path).
``channel`` is deliberately NOT included because ``tbl_messages``
doesn't carry that column (it lives on ``tbl_conversations``);
provider id formats are disjoint in practice (``mg:<uuid>``,
``wamid.HB...``, RFC ``<uuid@domain>``), so cross-provider
collision within one org is astronomically unlikely.

Because this constrains data across ALL inbound channels, the
migration runs a **probe query BEFORE** creating the index — if any
existing row-group already violates the new uniqueness, the
migration aborts with a ``RuntimeError`` naming the offending groups
so the operator can fix the data before re-running. The index would
otherwise raise ``UniqueViolation`` mid-CREATE anyway; the probe
just gives a clearer error message.

``CREATE INDEX CONCURRENTLY`` is used because ``tbl_messages`` is a
large hot table in production. ``CONCURRENTLY`` cannot run inside a
transaction, so the create is wrapped in ``autocommit_block()`` —
same pattern as ``0053``, ``0057``, ``0059``, ``0125``, ``0167``,
``0203``, ``0207``. ``IF NOT EXISTS`` makes the create idempotent
in case a prior run failed mid-flight (a failed CONCURRENTLY leaves
an INVALID index rather than nothing; documented as an operator
recovery step below).

**Operator recovery if this migration fails mid-CREATE:**
1. Check for INVALID indexes:
   ``SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;``
2. Drop any invalid ``uq_messages_org_channel_msgid``:
   ``DROP INDEX CONCURRENTLY uq_messages_org_channel_msgid;``
3. Re-run this migration.

Revision ID: 0214_messages_dedup_partial_idx
Revises:     0213_campaigns_smtp_sender
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0214_messages_dedup_partial_idx"
down_revision: Union[str, None] = "0213_campaigns_smtp_sender"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_messages_org_channel_msgid"

_PROBE_SQL = """
SELECT org_id, channel_message_id, COUNT(*) AS n
  FROM tbl_messages
 WHERE channel_message_id IS NOT NULL
 GROUP BY org_id, channel_message_id
HAVING COUNT(*) > 1
 LIMIT 10
"""


def upgrade() -> None:
    # Probe first — a clearer error than the mid-CREATE UniqueViolation
    # Postgres would raise on the second colliding row.
    bind = op.get_bind()
    rows = bind.exec_driver_sql(_PROBE_SQL).fetchall()
    if rows:
        # Compact-render the offending groups for the operator.
        formatted = "; ".join(
            f"org={r[0]} msg_id={r[1]!r} count={r[2]}" for r in rows
        )
        raise RuntimeError(
            f"tbl_messages contains {len(rows)} (org_id, "
            f"channel_message_id) group(s) with duplicate rows — cannot "
            f"add unique index. Fix these before re-running: {formatted}"
        )

    # CONCURRENTLY cannot run inside a transaction, so hop into
    # autocommit mode for this one statement. IF NOT EXISTS makes the
    # step re-runnable if a prior attempt left an INVALID index around.
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
                ON tbl_messages (org_id, channel_message_id)
                WHERE channel_message_id IS NOT NULL
            """
        )


def downgrade() -> None:
    # DROP INDEX CONCURRENTLY also cannot run inside a transaction.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
