"""billing — invoices + invoice_lines + payments + org_invoice_seq

Tables (all tenant-scoped, RLS-on):

  - `invoices`         — head; state machine (draft → issued → paid → void)
  - `invoice_lines`    — line items, FK → invoices, optional FK → catalog_items
  - `payments`         — payment records, FK → invoices
  - `org_invoice_seq`  — per-org row holding the last assigned invoice number

ENUMs:
  - `invoice_status`   (draft | issued | paid | void)
  - `payment_method`   (cash | card | upi | emi | cheque | bank)

Note: the step file mentions `0026_billing.py`; we're at 0028 because
0026 = custom_orders and 0027 = field_visits hopped before this. The
table layout is the same; only the alembic revision id changed.

Revision ID: 0028_billing
Revises: 0027_fp_field_visits
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0028_billing"
down_revision: Union[str, None] = "0027_fp_field_visits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUSES = ("draft", "issued", "paid", "void")
_METHODS = ("cash", "card", "upi", "emi", "cheque", "bank")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUSES, name="invoice_status", create_type=False
    )
    method_enum = postgresql.ENUM(
        *_METHODS, name="payment_method", create_type=False
    )
    bind = op.get_bind()
    status_enum.create(bind, checkfirst=True)
    method_enum.create(bind, checkfirst=True)

    # --- invoices ---
    op.create_table(
        "invoices",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=True),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "discount_amount",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total",
            sa.Numeric(14, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'INR'"),
            nullable=False,
        ),
        sa.Column("gst_number", sa.String(length=32), nullable=True),
        sa.Column("tax_rate_snapshot", sa.Numeric(5, 2), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_method", method_enum, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "subtotal >= 0", name="ck_invoices_subtotal_nonneg"
        ),
        sa.CheckConstraint(
            "tax_amount >= 0", name="ck_invoices_tax_nonneg"
        ),
        sa.CheckConstraint(
            "discount_amount >= 0", name="ck_invoices_discount_nonneg"
        ),
        sa.CheckConstraint("total >= 0", name="ck_invoices_total_nonneg"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoices_org_status", "invoices", ["org_id", "status"]
    )
    op.create_index("ix_invoices_contact", "invoices", ["contact_id"])
    op.create_index(
        "uq_invoices_org_number",
        "invoices",
        ["org_id", "number"],
        unique=True,
    )

    # --- invoice_lines ---
    op.create_table(
        "invoice_lines",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", UUID(as_uuid=True), nullable=False),
        sa.Column("catalog_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("line_subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "tax_pct",
            sa.Numeric(5, 2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("qty >= 1", name="ck_invoice_lines_qty_positive"),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_invoice_lines_unit_price_nonneg"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_lines_invoice", "invoice_lines", ["invoice_id"]
    )

    # --- payments ---
    op.create_table(
        "payments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("method", method_enum, nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])

    # --- org_invoice_seq (NOT TenantScoped: org_id is the PK) ---
    op.create_table(
        "org_invoice_seq",
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_number",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("org_id"),
    )

    apply_rls("invoices")
    apply_rls("invoice_lines")
    apply_rls("payments")
    # `org_invoice_seq.org_id` IS the tenant key — apply RLS on that
    # column name explicitly.
    apply_rls("org_invoice_seq", column="org_id")


def downgrade() -> None:
    drop_rls("org_invoice_seq")
    drop_rls("payments")
    drop_rls("invoice_lines")
    drop_rls("invoices")
    op.drop_table("org_invoice_seq")
    op.drop_index("ix_payments_invoice", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_invoice_lines_invoice", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("uq_invoices_org_number", table_name="invoices")
    op.drop_index("ix_invoices_contact", table_name="invoices")
    op.drop_index("ix_invoices_org_status", table_name="invoices")
    op.drop_table("invoices")
    bind = op.get_bind()
    postgresql.ENUM(name="payment_method").drop(bind, checkfirst=True)
    postgresql.ENUM(name="invoice_status").drop(bind, checkfirst=True)
