"""Add ``ai_prompt`` value to ``conversation_channel`` enum
(``tasks/ai-assistants`` Step 8).

The Instructions tab needs a bag of preset "AI Agent" / "Customer
Support Agent" / etc. prompts users can pick from a dropdown. We
store them in the central ``tbl_message_templates`` (Step-8
rationale: the templates module already handles versioning +
per-org isolation + import/export) discriminated by a new
``channel = 'ai_prompt'`` value.

Kept as a standalone ALTER migration because Postgres refuses to
use a newly-added enum value inside the same transaction that
added it. The follow-on data-backfill migration
``0204_bf_ai_prompt_templates`` uses this value in a separate
transaction.

Idempotent via ``IF NOT EXISTS`` — safe to re-run on a DB that
already has the value.

Chains after ``0202_bf_ai_assistants_perm``. Reversible only by
recreating the enum (Postgres has no ``DROP VALUE``); the
downgrade documents this limitation rather than silently doing
nothing.

Revision ID: 0203_ai_prompt_channel
Revises:     0202_bf_ai_assistants_perm
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0203_ai_prompt_channel"
down_revision: str | None = "0202_bf_ai_assistants_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres refuses to USE a newly-added enum value inside the
    # same transaction that added it (``UnsafeNewEnumValueUsageError``).
    # ``autocommit_block`` runs the ALTER TYPE outside Alembic's
    # per-migration transaction so the follow-on ``0204`` backfill
    # (which INSERTs rows referencing ``ai_prompt``) sees a fully
    # committed enum change.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE conversation_channel ADD VALUE IF NOT EXISTS 'ai_prompt'"
        )


def downgrade() -> None:
    # Postgres has no ``ALTER TYPE ... DROP VALUE``. The only safe
    # downgrade is to recreate the enum without the value, which
    # requires re-pointing every column that references it +
    # rebuilding every dependent view/function. Left as a no-op —
    # the value is inert when unused. If a true rollback is
    # required, DROP the enum via a hand-written migration after
    # unloading the two dependent tables (``tbl_conversations``,
    # ``tbl_message_templates``).
    pass
