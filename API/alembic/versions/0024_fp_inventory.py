"""fp_inventory — warehouses + items + movements + alerts

Four tenant-scoped, RLS-on tables for the furniture pack's inventory
module + four ENUMs. All tables are `fp_*` prefixed (first Layer-2
pack tables in the build).

CHECK constraints:
  - `fp_inventory_items.qty_on_hand >= 0`
  - `fp_inventory_items.qty_reserved >= 0`
  - `fp_inventory_items.qty_reserved <= qty_on_hand`
  - `fp_inventory_items.reorder_level >= 0`

Note: 0023 is `lead_sources` (Step 4.1). This migration is the next in
sequence; the step file mentions `0023_fp_inventory.py` because the
plan was written before the lead_sources hop existed in 4.1.

Revision ID: 0024_fp_inventory
Revises: 0023_lead_sources
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0024_fp_inventory"
down_revision: Union[str, None] = "0023_lead_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MOVEMENT_TYPES = ("receipt", "dispatch", "adjust", "transfer")
_ALERT_SEVERITY = ("low", "out")
_ALERT_PRIORITY = ("low", "med", "high")
_ALERT_STATUS = ("open", "ordered", "closed")


def upgrade() -> None:
    movement_enum = postgresql.ENUM(
        *_MOVEMENT_TYPES, name="fp_movement_type", create_type=False
    )
    severity_enum = postgresql.ENUM(
        *_ALERT_SEVERITY, name="fp_alert_severity", create_type=False
    )
    priority_enum = postgresql.ENUM(
        *_ALERT_PRIORITY, name="fp_alert_priority", create_type=False
    )
    status_enum = postgresql.ENUM(
        *_ALERT_STATUS, name="fp_alert_status", create_type=False
    )
    bind = op.get_bind()
    movement_enum.create(bind, checkfirst=True)
    severity_enum.create(bind, checkfirst=True)
    priority_enum.create(bind, checkfirst=True)
    status_enum.create(bind, checkfirst=True)

    # --- fp_warehouses ---
    op.create_table(
        "fp_warehouses",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
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
        sa.UniqueConstraint(
            "org_id", "name", name="uq_fp_warehouses_org_name"
        ),
    )

    # --- fp_inventory_items ---
    op.create_table(
        "fp_inventory_items",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("warehouse_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("material", sa.String(length=64), nullable=True),
        sa.Column("color", sa.String(length=64), nullable=True),
        sa.Column("finish", sa.String(length=64), nullable=True),
        sa.Column(
            "dimensions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "qty_on_hand",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "qty_reserved",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reorder_level",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "last_received_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "custom_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_best_seller",
            sa.Boolean(),
            server_default=sa.text("false"),
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
        sa.CheckConstraint(
            "qty_on_hand >= 0",
            name="ck_fp_inventory_items_qty_on_hand_nonneg",
        ),
        sa.CheckConstraint(
            "qty_reserved >= 0",
            name="ck_fp_inventory_items_qty_reserved_nonneg",
        ),
        sa.CheckConstraint(
            "qty_reserved <= qty_on_hand",
            name="ck_fp_inventory_items_reserved_le_on_hand",
        ),
        sa.CheckConstraint(
            "reorder_level >= 0",
            name="ck_fp_inventory_items_reorder_nonneg",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["fp_warehouses.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "warehouse_id", "sku",
            name="uq_fp_inventory_items_warehouse_sku",
        ),
    )
    op.create_index(
        "ix_fp_inventory_items_warehouse",
        "fp_inventory_items",
        ["warehouse_id"],
    )
    op.create_index(
        "ix_fp_inventory_items_catalog",
        "fp_inventory_items",
        ["catalog_item_id"],
    )

    # --- fp_inventory_movements ---
    op.create_table(
        "fp_inventory_movements",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", movement_enum, nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "reference_type", sa.String(length=64), nullable=True
        ),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["fp_inventory_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_inventory_movements_item_created",
        "fp_inventory_movements",
        ["item_id", "created_at"],
    )

    # --- fp_inventory_alerts ---
    op.create_table(
        "fp_inventory_alerts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), nullable=False),
        sa.Column("severity", severity_enum, nullable=False),
        sa.Column(
            "priority",
            priority_enum,
            server_default=sa.text("'med'"),
            nullable=False,
        ),
        sa.Column(
            "suggested_reorder_qty",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["fp_inventory_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_inventory_alerts_item_status",
        "fp_inventory_alerts",
        ["item_id", "status"],
    )

    apply_rls("fp_warehouses")
    apply_rls("fp_inventory_items")
    apply_rls("fp_inventory_movements")
    apply_rls("fp_inventory_alerts")


def downgrade() -> None:
    drop_rls("fp_inventory_alerts")
    drop_rls("fp_inventory_movements")
    drop_rls("fp_inventory_items")
    drop_rls("fp_warehouses")
    op.drop_index(
        "ix_fp_inventory_alerts_item_status",
        table_name="fp_inventory_alerts",
    )
    op.drop_table("fp_inventory_alerts")
    op.drop_index(
        "ix_fp_inventory_movements_item_created",
        table_name="fp_inventory_movements",
    )
    op.drop_table("fp_inventory_movements")
    op.drop_index(
        "ix_fp_inventory_items_catalog", table_name="fp_inventory_items"
    )
    op.drop_index(
        "ix_fp_inventory_items_warehouse",
        table_name="fp_inventory_items",
    )
    op.drop_table("fp_inventory_items")
    op.drop_table("fp_warehouses")
    bind = op.get_bind()
    postgresql.ENUM(name="fp_alert_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fp_alert_priority").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fp_alert_severity").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fp_movement_type").drop(bind, checkfirst=True)
