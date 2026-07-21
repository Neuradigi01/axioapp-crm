"""Functional index on digit-only phone for import dedup.

The leads-import dedupe path (``leads/imports/dedup.py::resolve_existing_contact``)
runs ``regexp_replace(coalesce(phone,''), '\\D', '', 'g') = :phone_norm``
per CSV row. Without a functional index this is a full-table scan
per row — for a 50k-row import against a 10k-contact org that's 500M
regex ops.

This migration adds a functional B-tree index on the same expression
per org so Postgres can use an index scan. Additive + reversible.

Revision ID: 0168_phone_dedup_index
Revises:     0167_walk_in_lead_source
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0168_phone_dedup_index"
down_revision: str | None = "0167_walk_in_lead_source"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_phone_digits "
        "ON tbl_contacts ("
        "  org_id, "
        "  (regexp_replace(coalesce(phone, ''), '\\D', '', 'g'))"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_phone_digits")
