"""catalog_items

Creates the bare-minimum `catalog_items` table (tenant-scoped, RLS-on)
with a unique `(org_id, sku)` constraint and a composite index on
`(org_id, category)` to make the category filter index-only.

Phase 4's furniture pack will add `fp_inventory_items` to extend this
with stock movements / multi-location; this table is the universal
"product interest" lookup core modules can reference today.

Revision ID: 0015_catalog_items
Revises: 0014_walk_ins
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0015_catalog_items"
down_revision: Union[str, None] = "0014_walk_ins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'INR'"),
            nullable=False,
        ),
        sa.Column(
            "custom_data",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "sku", name="uq_catalog_items_org_sku"),
    )
    op.create_index(
        "ix_catalog_items_org_id", "catalog_items", ["org_id"]
    )
    op.create_index(
        "ix_catalog_items_org_category",
        "catalog_items",
        ["org_id", "category"],
    )

    apply_rls("catalog_items")


def downgrade() -> None:
    drop_rls("catalog_items")
    op.drop_index(
        "ix_catalog_items_org_category", table_name="catalog_items"
    )
    op.drop_index("ix_catalog_items_org_id", table_name="catalog_items")
    op.drop_table("catalog_items")
