"""catalog extensions: category entity + additive item columns.

Ships every backend piece the catalog review calls out:

  * ``tbl_catalog_categories`` (new) — first-class category entity per
    org. Replaces the free-text ``tbl_catalog_items.category`` column
    with a proper FK. Bringing the free-text column across so existing
    code paths keep working; it becomes a display fallback only. C2.
  * Backfill from the free-text column → new category rows → item
    ``category_id`` FK. Idempotent (``ON CONFLICT DO NOTHING``).
  * Additive columns on ``tbl_catalog_items``:
      - ``description`` TEXT NULL — long-form product notes (C4)
      - ``cost_price`` NUMERIC(14, 2) NULL — cost for margin analytics (C6)
      - ``tags`` TEXT[] NOT NULL DEFAULT '{}' — free-form labels (C13)
      - ``image_urls`` TEXT[] NOT NULL DEFAULT '{}' — gallery beyond the
        primary ``image_url`` (C5)
      - ``category_id`` UUID NULL FK → tbl_catalog_categories
        ON DELETE SET NULL

Downgrade drops each of the six columns + the new table + index cleanly.
The free-text ``category`` column stays across upgrade *and* downgrade
so downgrade doesn't lose data.

Revision ID: 0163_catalog_extensions
Revises:     0162_tasks_custom_data
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0163_catalog_extensions"
down_revision: Union[str, None] = "0162_tasks_custom_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. new tbl_catalog_categories -------------------------------------
    op.create_table(
        "tbl_catalog_categories",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon_emoji", sa.String(length=8), nullable=True),
        sa.Column("color_hex", sa.String(length=7), nullable=True),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_catalog_categories_org_name"),
    )
    op.create_index(
        "ix_catalog_categories_org_order",
        "tbl_catalog_categories",
        ["org_id", "display_order"],
    )

    # --- 2. additive columns on tbl_catalog_items --------------------------
    op.add_column("tbl_catalog_items", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "tbl_catalog_items",
        sa.Column("cost_price", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "tbl_catalog_items",
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "tbl_catalog_items",
        sa.Column(
            "image_urls",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "tbl_catalog_items",
        sa.Column(
            "category_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_catalog_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_catalog_items_category_id",
        "tbl_catalog_items",
        ["category_id"],
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )

    # --- 3. backfill categories from existing free-text values -------------
    # Insert one row per distinct (org_id, category) pair. Slug is a
    # lower-cased hyphenated variant; not unique-constrained so a
    # collision falls through cleanly. Idempotent via ON CONFLICT.
    op.execute(
        """
        INSERT INTO tbl_catalog_categories (org_id, name, slug)
        SELECT DISTINCT
          i.org_id,
          i.category,
          lower(regexp_replace(i.category, '[^a-zA-Z0-9]+', '-', 'g'))
        FROM tbl_catalog_items i
        WHERE i.category IS NOT NULL AND i.category <> ''
        ON CONFLICT (org_id, name) DO NOTHING
        """
    )

    # --- 4. link items to their newly-created categories -------------------
    op.execute(
        """
        UPDATE tbl_catalog_items i
        SET category_id = c.id
        FROM tbl_catalog_categories c
        WHERE i.org_id = c.org_id
          AND i.category = c.name
          AND i.category_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_items_category_id", table_name="tbl_catalog_items")
    op.drop_column("tbl_catalog_items", "category_id")
    op.drop_column("tbl_catalog_items", "image_urls")
    op.drop_column("tbl_catalog_items", "tags")
    op.drop_column("tbl_catalog_items", "cost_price")
    op.drop_column("tbl_catalog_items", "description")
    op.drop_index("ix_catalog_categories_org_order", table_name="tbl_catalog_categories")
    op.drop_table("tbl_catalog_categories")
