"""Data-access layer for the core billing module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations cover the three tables this module owns:

  * ``tbl_invoices``           — list/get/insert/delete + the per-org
    sequence allocator ``next_invoice_number`` (PostgreSQL upsert with
    RETURNING).
  * ``tbl_invoice_lines``      — list/get/insert/delete.
  * ``tbl_payments``           — list/insert + ``sum_payments`` for the
    paid-so-far recompute that triggers the ``issued → paid`` transition.

The state-machine validation, tax-rate snapshotting, total recomputation,
and audit emits all live in ``service.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.billing.models import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    OrgInvoiceSeq,
    Payment,
)
from src.app.shared.db.pagination import paginate

# --- invoice reads ------------------------------------------------------


async def get_invoice_by_id(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(Invoice).where(Invoice.id == invoice_id))
    return result.scalar_one_or_none()


async def list_invoices_query(
    session: AsyncSession,
    *,
    status_filter: InvoiceStatus | None = None,
    contact_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Invoice], int]:
    """Filterable paginated list, newest first."""
    base = select(Invoice)
    if status_filter is not None:
        base = base.where(Invoice.status == status_filter)
    if contact_id is not None:
        base = base.where(Invoice.contact_id == contact_id)
    base = base.order_by(Invoice.created_at.desc())
    return await paginate(session, base, page=page, size=size)


# --- invoice line reads -------------------------------------------------


async def list_invoice_lines(session: AsyncSession, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    """All lines on one invoice, oldest first (preserves authoring
    order in the invoice viewer)."""
    rows = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice_id)
                .order_by(InvoiceLine.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_invoice_line(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> InvoiceLine | None:
    """Single-line read scoped to its parent invoice — refuses a
    cross-invoice line id even when the row exists."""
    return (
        await session.execute(
            select(InvoiceLine).where(
                InvoiceLine.id == line_id,
                InvoiceLine.invoice_id == invoice_id,
            )
        )
    ).scalar_one_or_none()


# --- payment reads ------------------------------------------------------


async def list_payments_query(session: AsyncSession, *, invoice_id: uuid.UUID) -> list[Payment]:
    """All payments against one invoice, oldest first."""
    rows = (
        (
            await session.execute(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.received_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def find_overdue(
    session: AsyncSession,
    *,
    days_overdue: int,
) -> list[Invoice]:
    """Return ``issued`` invoices whose ``issued_at`` is more than
    ``days_overdue`` days ago.

    Used by ``core.billing.tasks.scan_for_overdue`` to drive
    ``invoice.overdue_7d`` events. The scanner is cross-tenant — it
    opens a session WITHOUT setting ``RequestContext.org_id`` so the
    ``do_orm_execute`` tenant filter is a no-op + the scan returns
    every org's rows in one pass; the caller reads ``inv.org_id`` off
    each row + supplies it when publishing.

    Invoices in ``draft`` / ``paid`` / ``void`` are excluded — only
    open issued invoices warrant an overdue reminder. Without a
    dedicated ``due_date`` column on ``tbl_invoices`` we treat
    ``issued_at + days_overdue`` as the overdue threshold (industry
    default Net-7 / Net-30 alignment).
    """
    cutoff = datetime.now(UTC) - timedelta(days=days_overdue)
    stmt = (
        select(Invoice)
        .where(Invoice.status == InvoiceStatus.issued)
        .where(Invoice.issued_at.is_not(None))
        .where(Invoice.issued_at < cutoff)
    )
    return list((await session.execute(stmt)).scalars().all())


async def sum_payments(session: AsyncSession, invoice_id: uuid.UUID) -> Decimal:
    """Sum of all payment amounts against one invoice. Returns
    ``Decimal('0')`` when the invoice has no payments yet — caller
    uses this to decide whether the invoice has fully settled and
    should flip to ``paid``."""
    result = await session.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice_id)
    )
    return Decimal(result.scalar_one())


# --- sequence allocator -------------------------------------------------


async def next_invoice_number(session: AsyncSession, *, org_id: uuid.UUID) -> int:
    """Atomically allocate the next per-org invoice number.

    Uses ``INSERT ... ON CONFLICT DO UPDATE`` so the row is created on
    first issue, and ``RETURNING last_number`` gives the freshly
    incremented value. The composite (insert OR update) acquires a row
    lock for the duration of the transaction — concurrent issuers
    serialize at the org level, which is fine for POS throughput.
    """
    stmt = (
        pg_insert(OrgInvoiceSeq)
        .values(org_id=org_id, last_number=1)
        .on_conflict_do_update(
            index_elements=[OrgInvoiceSeq.org_id],
            set_={"last_number": OrgInvoiceSeq.last_number + 1},
        )
        .returning(OrgInvoiceSeq.last_number)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


# --- writes (caller commits) --------------------------------------------


def insert_invoice(session: AsyncSession, invoice: Invoice) -> None:
    """Register an already-constructed Invoice for INSERT."""
    session.add(invoice)


def insert_invoice_line(session: AsyncSession, line: InvoiceLine) -> None:
    """Register an already-constructed InvoiceLine for INSERT."""
    session.add(line)


def insert_payment(session: AsyncSession, payment: Payment) -> None:
    """Register an already-constructed Payment for INSERT."""
    session.add(payment)


async def delete_invoice_row(session: AsyncSession, invoice: Invoice) -> None:
    """Mark an Invoice row for DELETE. Caller commits."""
    await session.delete(invoice)


async def delete_invoice_line(session: AsyncSession, line: InvoiceLine) -> None:
    """Mark an InvoiceLine row for DELETE. Caller commits."""
    await session.delete(line)


__all__ = [
    "delete_invoice_line",
    "delete_invoice_row",
    "get_invoice_by_id",
    "get_invoice_line",
    "insert_invoice",
    "insert_invoice_line",
    "insert_payment",
    "list_invoice_lines",
    "list_invoices_query",
    "list_payments_query",
    "next_invoice_number",
    "sum_payments",
]
