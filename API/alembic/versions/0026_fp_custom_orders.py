"""fp_custom_orders — orders + measurements + photos + stage history

Four tenant-scoped, RLS-on tables for the furniture pack's custom-orders
module:

  - `fp_custom_orders`              — head of a bespoke build
  - `fp_custom_order_measurements`  — captured dimensions per order
  - `fp_custom_order_photos`        — site visit / progress photos
  - `fp_custom_order_stages`        — append-only stage transition ledger

Stage transitions go through the core `pipelines.move_card` engine
(seeded `custom_orders` pipeline in pack.yaml). The per-order
`fp_custom_order_stages` rows are a module-specific funnel-analytics
trail, on top of the activity + audit rows the engine writes.

Revision ID: 0026_fp_custom_orders
Revises: 0025_fp_inventory_cover_url
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0026_fp_custom_orders"
down_revision: Union[str, None] = "0025_fp_inventory_cover_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- fp_custom_orders ---
    op.create_table(
        "fp_custom_orders",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=True),
        sa.Column(
            "materials",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("color", sa.String(length=64), nullable=True),
        sa.Column("finish", sa.String(length=64), nullable=True),
        sa.Column(
            "pipeline_stage",
            sa.String(length=64),
            server_default=sa.text("'measurement_scheduled'"),
            nullable=False,
        ),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "total_amount",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "advance_paid",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "custom_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
            "total_amount >= 0",
            name="ck_fp_custom_orders_total_nonneg",
        ),
        sa.CheckConstraint(
            "advance_paid >= 0",
            name="ck_fp_custom_orders_advance_nonneg",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_custom_orders_org_stage",
        "fp_custom_orders",
        ["org_id", "pipeline_stage"],
    )
    op.create_index(
        "ix_fp_custom_orders_contact",
        "fp_custom_orders",
        ["contact_id"],
    )
    op.create_index(
        "ix_fp_custom_orders_lead",
        "fp_custom_orders",
        ["lead_id"],
    )

    # --- fp_custom_order_measurements ---
    op.create_table(
        "fp_custom_order_measurements",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("item_label", sa.String(length=128), nullable=False),
        sa.Column("length_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("width_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("height_cm", sa.Numeric(8, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["order_id"], ["fp_custom_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_custom_order_measurements_order",
        "fp_custom_order_measurements",
        ["order_id"],
    )

    # --- fp_custom_order_photos ---
    op.create_table(
        "fp_custom_order_photos",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.String(length=255), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
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
            ["order_id"], ["fp_custom_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_custom_order_photos_order",
        "fp_custom_order_photos",
        ["order_id"],
    )

    # --- fp_custom_order_stages ---
    op.create_table(
        "fp_custom_order_stages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_stage", sa.String(length=64), nullable=True),
        sa.Column("to_stage", sa.String(length=64), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["fp_custom_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_custom_order_stages_order_changed",
        "fp_custom_order_stages",
        ["order_id", "changed_at"],
    )

    apply_rls("fp_custom_orders")
    apply_rls("fp_custom_order_measurements")
    apply_rls("fp_custom_order_photos")
    apply_rls("fp_custom_order_stages")


def downgrade() -> None:
    drop_rls("fp_custom_order_stages")
    drop_rls("fp_custom_order_photos")
    drop_rls("fp_custom_order_measurements")
    drop_rls("fp_custom_orders")
    op.drop_index(
        "ix_fp_custom_order_stages_order_changed",
        table_name="fp_custom_order_stages",
    )
    op.drop_table("fp_custom_order_stages")
    op.drop_index(
        "ix_fp_custom_order_photos_order",
        table_name="fp_custom_order_photos",
    )
    op.drop_table("fp_custom_order_photos")
    op.drop_index(
        "ix_fp_custom_order_measurements_order",
        table_name="fp_custom_order_measurements",
    )
    op.drop_table("fp_custom_order_measurements")
    op.drop_index(
        "ix_fp_custom_orders_lead", table_name="fp_custom_orders"
    )
    op.drop_index(
        "ix_fp_custom_orders_contact", table_name="fp_custom_orders"
    )
    op.drop_index(
        "ix_fp_custom_orders_org_stage", table_name="fp_custom_orders"
    )
    op.drop_table("fp_custom_orders")
