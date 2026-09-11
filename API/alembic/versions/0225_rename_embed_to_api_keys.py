"""Rename ``tbl_embed_keys`` → ``tbl_api_keys`` + rename dependent
indexes and CHECK constraints (``tasks/custom-events`` Step 1
continuation).

Follows the Step 1 additive-column migration (``0224``). Together
these two migrations complete Step 1's contract: the table is now a
proper multi-resource API-key table (embed lead-forms, ai-assistants,
events) with the columns each surface needs. Step 2 folds the code
into ``core/public_ingest/``.

**Runtime-critical changes.** The rename is a pure schema rename —
data is untouched. Every existing row keeps its ``resource_type`` +
key hash + policies. The RLS policy (``org_isolation``) is attached
to the relation by OID, so it survives the ``ALTER TABLE ... RENAME``
automatically (verified by Postgres docs and by round-trip test).

Indexes + constraints get renamed too so the schema reads cleanly
after the migration:

  * Table: ``tbl_embed_keys`` → ``tbl_api_keys``.
  * PK constraint: ``tbl_embed_keys_pkey`` → auto-renamed by
    Postgres to ``tbl_api_keys_pkey`` when the table renames.
  * Named indexes explicitly renamed to their ``api_keys`` equivalents.
  * CHECK constraints explicitly renamed.

Reversible: downgrade renames everything back.

Revision ID: 0225_rename_embed_to_api_keys
Revises:     0224_api_keys_events_scope
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0225_rename_embed_to_api_keys"
down_revision: str | None = "0224_api_keys_events_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Named indexes to rename. PK constraint index (``tbl_embed_keys_pkey``)
# renames automatically with the table so it's not listed here.
_INDEX_RENAMES: tuple[tuple[str, str], ...] = (
    ("ix_tbl_embed_keys_prefix_live", "ix_tbl_api_keys_prefix_live"),
    ("ix_tbl_embed_keys_org_created", "ix_tbl_api_keys_org_created"),
    ("ix_embed_keys_resource", "ix_api_keys_resource"),
    ("ix_embed_keys_grace_expires_at", "ix_api_keys_grace_expires_at"),
    ("ix_embed_keys_lookup_hash", "ix_api_keys_lookup_hash"),
)

_CHECK_RENAMES: tuple[tuple[str, str], ...] = (
    ("ck_embed_keys_resource_type", "ck_api_keys_resource_type"),
    ("ck_embed_keys_mode", "ck_api_keys_mode"),
)


def upgrade() -> None:
    op.rename_table("tbl_embed_keys", "tbl_api_keys")

    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    for old_name, new_name in _CHECK_RENAMES:
        op.execute(
            f"ALTER TABLE tbl_api_keys RENAME CONSTRAINT {old_name} TO {new_name}"
        )


def downgrade() -> None:
    for old_name, new_name in _CHECK_RENAMES:
        op.execute(
            f"ALTER TABLE tbl_api_keys RENAME CONSTRAINT {new_name} TO {old_name}"
        )

    for old_name, new_name in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {new_name} RENAME TO {old_name}")

    op.rename_table("tbl_api_keys", "tbl_embed_keys")
