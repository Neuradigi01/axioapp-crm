"""Core billing engine — generic across packs.

Three tenant-scoped, RLS-on tables:

- `Invoice` — head of one customer charge. State machine: draft →
  issued → paid → void. `number` is org-unique and assigned at issue
  time; `gst_number` + `tax_rate_snapshot` are snapshotted at issue
  time so historical invoices remain accurate even after the org
  edits its settings.
- `InvoiceLine` — line items. `catalog_item_id` is nullable so
  ad-hoc lines ("delivery charge") work without polluting the
  catalog.
- `Payment` — payment records linked to an invoice. An invoice flips
  to `status='paid'` once the sum of payments meets the total.

Plus a small `org_invoice_seq(org_id, last_number)` table that backs
the per-org invoice number sequence (Postgres sequences can't be
scoped to a tenant cheaply).

`core/` knows nothing about furniture — the pack provides the PDF
template and the POS endpoint on top.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    issued = "issued"
    paid = "paid"
    void = "void"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    card = "card"
    upi = "upi"
    emi = "emi"
    cheque = "cheque"
    bank = "bank"


invoice_status_enum = ENUM(
    InvoiceStatus,
    name="invoice_status",
    values_callable=lambda obj: [m.value for m in obj],
)

payment_method_enum = ENUM(
    PaymentMethod,
    name="payment_method",
    values_callable=lambda obj: [m.value for m in obj],
)


class Invoice(Base, TenantScoped):
    __tablename__ = "tbl_invoices"
    __table_args__ = (
        Index("ix_invoices_org_status", "org_id", "status"),
        Index("ix_invoices_contact", "contact_id"),
        Index(
            "uq_invoices_org_number",
            "org_id",
            "number",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # NULL while still a draft; assigned via org_invoice_seq at issue time.
    number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        invoice_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=sql_text("0")
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=sql_text("'INR'")
    )
    # Snapshot of org settings at issue time — historical record.
    gst_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(payment_method_enum, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )


class InvoiceLine(Base, TenantScoped):
    __tablename__ = "tbl_invoice_lines"
    __table_args__ = (Index("ix_invoice_lines_invoice", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_catalog_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=sql_text("0")
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class Payment(Base, TenantScoped):
    __tablename__ = "tbl_payments"
    __table_args__ = (Index("ix_payments_invoice", "invoice_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(payment_method_enum, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class OrgInvoiceSeq(Base):
    """Per-org invoice-number counter.

    One row per `org_id` carrying the last assigned number. `issue()`
    does `SELECT ... FOR UPDATE` on the row, increments
    `last_number`, and uses it. The lock is released at transaction
    commit so concurrent issues serialize at the org level — fine for
    POS throughput.

    This table is intentionally NOT TenantScoped: the row IS the
    tenant key, and RLS is applied at the migration level instead.
    """

    __tablename__ = "tbl_org_invoice_seq"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_number: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=sql_text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )
