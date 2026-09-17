"""Contact-import default source — batch-level fallback for CSV rows
whose "source" column is missing or blank.

Adds ``tbl_contact_imports.default_source`` (nullable VARCHAR(64)).
The wizard's map step surfaces a "Default source for this import"
picker; the value is persisted here and read by the commit worker,
which uses it as the fallback when a row's mapped ``source`` cell is
empty. NULL preserves the pre-existing behaviour (rows keep whatever
the CSV provided, empty stays empty).

Revision ID: 0229_import_default_source
Revises:     0228_multi_entity_events
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0229_import_default_source"
down_revision: str | None = "0228_multi_entity_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_contact_imports",
        sa.Column("default_source", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_contact_imports", "default_source")
