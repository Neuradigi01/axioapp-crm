"""Add ``ai_assistant`` to the ``lead_source`` Postgres enum
(``tasks/ai-assistants`` Step 16).

Step 16's auto-lead-capture flow creates leads with
``source=LeadSource.ai_assistant`` when a visitor mentions an
email in a chat turn (``lead_capture_mode='detect_email'``) or
answers the turn-N ask (``mode='ask_at_turn'``). Adding the enum
value in its own migration + own transaction is required because
Postgres refuses to reference a newly-added enum value inside the
same tx that added it (``UnsafeNewEnumValueUsageError``). The
``autocommit_block`` sidesteps this.

Chains after ``0206_ai_lead_capture`` (the ai_assistants schema
change) so downgrade order is symmetric.

Revision ID: 0207_add_ai_asst_leadsrc
Revises:     0206_ai_lead_capture
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0207_add_ai_asst_leadsrc"
down_revision: str | None = "0206_ai_lead_capture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
    # block (PG refuses to reference the freshly-added value in the
    # same tx). ``get_context().autocommit_block()`` is the alembic-
    # sanctioned escape hatch.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE lead_source ADD VALUE IF NOT EXISTS 'ai_assistant'")


def downgrade() -> None:
    # Postgres has no DROP VALUE — a downgrade would require
    # rebuilding the enum type + rewriting every column that
    # references it. Deliberately a no-op; the extra enum value
    # is harmless on a downgraded schema (no rows reference it
    # until Step 16 lands again).
    pass
