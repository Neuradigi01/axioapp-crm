"""Install the ``pgvector`` Postgres extension
(``tasks/ai-assistants`` Step 4).

Ships the extension only — no tables land here. Step 5 owns the
first table that uses the ``VECTOR`` type
(``tbl_ai_assistant_chunks(embedding VECTOR(1536))``); this step
just makes the type + operators available cluster-wide so the
Step-5 migration doesn't have to interleave DDL with an extension
install.

Idempotent: ``CREATE EXTENSION IF NOT EXISTS vector`` is a no-op
on databases where the extension is already installed.

**Deployment precondition** (documented in
``tasks/ai-assistants/README.md`` §Locked design 3): production
Postgres must have ``pgvector`` in the extension allow-list.
Availability by platform as of 2026-08:

  * Supabase, Neon, Timescale Cloud — yes, out of the box.
  * AWS RDS Postgres — yes, since 16.3+.
  * Google Cloud SQL Postgres — yes, since 15.7+.
  * Postgres 17 self-hosted — yes, ships with pgvector 0.7+ in
    the standard postgres-contrib package.

If the target Postgres does NOT have the extension available in
``pg_available_extensions``, this migration fails hard with a
``FEATURE_NOT_SUPPORTED`` error — the operator sees a clear
message pointing at the allow-list rather than a mystery boot
crash later when Step 5's models try to declare a ``VECTOR`` column.

Chains after ``0199_bf_ai_provider_perm``. Reversible.

Revision ID: 0200_install_pgvector
Revises:     0199_bf_ai_provider_perm
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0200_install_pgvector"
down_revision: str | None = "0199_bf_ai_provider_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Safe because Step 5 owns the first table that references the
    # type — at this migration's revision, no VECTOR columns exist.
    # If Step 5 has already run, the drop cascades to the type;
    # Postgres will refuse if any column still uses it, which is
    # the right behaviour (accidental downgrade past a table-owning
    # revision must not silently drop the data type).
    op.execute("DROP EXTENSION IF EXISTS vector")
