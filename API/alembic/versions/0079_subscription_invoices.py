"""subscription_invoices table — local mirror of Stripe invoices.

Step 13's webhook handlers (sub-step 13.b) upsert into this table on
`invoice.paid` / `invoice.payment_failed` / `invoice.finalized`
events. The billing-settings page (Step 16) reads this list for the
in-app invoice history; clicking through to `hosted_invoice_url` or
`pdf_url` hands the user back to Stripe-hosted UI for the actual
document.

`stripe_invoice_id` is UNIQUE — webhooks rely on it for the upsert
target. `org_id` is FK + indexed so the per-org list query is cheap.
RLS uses the standard `apply_rls` helper.

Revision ID: 0079_subscription_invoices
Revises:     0078_subs_pending_checkout
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0079_subscription_invoices"
down_revision: Union[str, None] = "0078_subs_pending_checkout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_invoices",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_invoice_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("amount_due_cents", sa.Integer(), nullable=False),
        sa.Column("amount_paid_cents", sa.Integer(), nullable=False),
        sa.Column(
            "currency",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hosted_invoice_url", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('paid', 'open', 'void', 'uncollectible', 'draft')",
            name="subscription_invoices_status_check",
        ),
        sa.UniqueConstraint(
            "stripe_invoice_id",
            name="subscription_invoices_stripe_id_uq",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # `TenantScoped`'s implicit `index=True` produces this name when
    # `create_all` is used in tests; declare it explicitly so the
    # production schema matches.
    op.create_index(
        "ix_subscription_invoices_org_id", "subscription_invoices", ["org_id"]
    )
    op.create_index(
        "ix_subscription_invoices_subscription_id",
        "subscription_invoices",
        ["subscription_id"],
    )

    apply_rls("subscription_invoices")


def downgrade() -> None:
    drop_rls("subscription_invoices")
    op.drop_index(
        "ix_subscription_invoices_subscription_id",
        table_name="subscription_invoices",
    )
    op.drop_index(
        "ix_subscription_invoices_org_id", table_name="subscription_invoices"
    )
    op.drop_table("subscription_invoices")
