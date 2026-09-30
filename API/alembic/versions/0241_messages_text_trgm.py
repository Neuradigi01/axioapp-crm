"""Trigram index on message bodies for inbox search.

The Conversations inbox search now matches message text (in addition
to the channel handle and the linked contact's name / phone / email).
A GIN ``gin_trgm_ops`` index lets ``text ILIKE '%term%'`` use an index
scan instead of reading every message row. ``pg_trgm`` is already
installed by 0007_contacts.

Revision ID: 0241_messages_text_trgm
Revises:     0240_base_call_outcomes
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0241_messages_text_trgm"
down_revision: str | None = "0240_base_call_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_text_trgm "
        "ON tbl_messages USING gin (text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_text_trgm")
