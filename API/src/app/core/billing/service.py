"""Service layer for the core billing engine.

State machine:

  draft ──issue──▶ issued ──record_payment(s)──▶ paid
                       │
                       └──void──▶ void

Once an invoice is `issued` its lines are frozen — `add_line` /
`update_line` only work on drafts. `void` is the escape hatch for
issued/paid invoices (e.g. mistake-after-print); we keep the row so
the org-unique `number` doesn't get re-used.

Tax + GST are snapshotted at `issue()` time from `org_settings`:

  - tax_rate_snapshot   ← org_settings.tax_rate
  - gst_number          ← org_settings.gst_number

Historical invoices stay accurate even if the org later edits its
settings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.app.core import audit
from src.app.core.billing.models import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    OrgInvoiceSeq,
    Payment,
    PaymentMethod,
)
from src.app.core.billing.schemas import (
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceUpdate,
    PaymentCreate,
)
from src.app.core.settings.service import get_or_create as get_org_settings
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import ensure_found, get_or_404


# --- reads ----------------------------------------------------------------


async def list_invoices(
    session: AsyncSession,
    *,
    status_filter: Optional[InvoiceStatus] = None,
    contact_id: Optional[uuid.UUID] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Invoice], int]:
    filters = []
    if status_filter is not None:
        filters.append(Invoice.status == status_filter)
    if contact_id is not None:
        filters.append(Invoice.contact_id == contact_id)

    base = select(Invoice)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(Invoice.created_at.desc())

    return await paginate(session, base, page=page, size=size)


async def get_invoice(
    session: AsyncSession, invoice_id: uuid.UUID
) -> Invoice:
    return await get_or_404(session, Invoice, invoice_id, entity="invoice")


async def get_invoice_with_lines(
    session: AsyncSession, invoice_id: uuid.UUID
) -> tuple[Invoice, list[InvoiceLine]]:
    invoice = await get_invoice(session, invoice_id)
    lines = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice.id)
                .order_by(InvoiceLine.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return invoice, list(lines)


async def list_payments(
    session: AsyncSession, *, invoice_id: uuid.UUID
) -> list[Payment]:
    rows = (
        await session.execute(
            select(Payment)
            .where(Payment.invoice_id == invoice_id)
            .order_by(Payment.received_at.asc())
        )
    ).scalars().all()
    return list(rows)


# --- writes ---------------------------------------------------------------


async def create_draft(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: InvoiceCreate,
) -> Invoice:
    settings = await get_org_settings(session, org_id=org_id)
    inv = Invoice(
        org_id=org_id,
        contact_id=payload.contact_id,
        status=InvoiceStatus.draft,
        currency=settings.currency,
        notes=payload.notes,
        custom_data=payload.custom_data,
    )
    session.add(inv)
    await session.commit()
    await session.refresh(inv)

    await audit.log(
        "billing.invoice_created",
        entity_type="invoice",
        entity_id=inv.id,
        after={"status": inv.status.value},
        user_id=user_id,
    )
    return inv


async def update_invoice(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
) -> Invoice:
    inv = await get_invoice(session, invoice_id)
    if inv.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"invoice {inv.id} is {inv.status.value}, only drafts are "
                "editable"
            ),
        )
    changed = False
    for field in ("contact_id", "discount_amount", "notes", "custom_data"):
        v = getattr(payload, field)
        if v is not None:
            setattr(inv, field, v)
            changed = True
    if changed:
        _recompute_totals(inv, await _load_lines(session, inv.id))
        await session.commit()
        await session.refresh(inv)
    return inv


async def delete_invoice(
    session: AsyncSession, *, invoice_id: uuid.UUID
) -> None:
    inv = await get_invoice(session, invoice_id)
    if inv.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only draft invoices can be deleted; void issued ones instead",
        )
    await session.delete(inv)
    await session.commit()


async def add_line(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    payload: InvoiceLineCreate,
) -> InvoiceLine:
    inv = await get_invoice(session, invoice_id)
    if inv.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot add lines to a non-draft invoice",
        )
    settings = await get_org_settings(session, org_id=inv.org_id)
    tax_pct = payload.tax_pct if payload.tax_pct is not None else settings.tax_rate

    line_subtotal = (payload.unit_price * payload.qty).quantize(Decimal("0.01"))
    line_tax = (line_subtotal * tax_pct / Decimal("100")).quantize(Decimal("0.01"))
    line_total = (line_subtotal + line_tax).quantize(Decimal("0.01"))

    line = InvoiceLine(
        org_id=inv.org_id,
        invoice_id=inv.id,
        catalog_item_id=payload.catalog_item_id,
        description=payload.description,
        qty=payload.qty,
        unit_price=payload.unit_price,
        line_subtotal=line_subtotal,
        tax_pct=tax_pct,
        line_total=line_total,
    )
    session.add(line)
    await session.flush()

    lines = await _load_lines(session, inv.id)
    _recompute_totals(inv, lines)
    await session.commit()
    await session.refresh(line)
    return line


async def remove_line(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    inv = await get_invoice(session, invoice_id)
    if inv.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot remove lines from a non-draft invoice",
        )
    line = (
        await session.execute(
            select(InvoiceLine).where(
                InvoiceLine.id == line_id,
                InvoiceLine.invoice_id == invoice_id,
            )
        )
    ).scalar_one_or_none()
    line = ensure_found(line, entity="line")
    await session.delete(line)
    await session.flush()
    lines = await _load_lines(session, inv.id)
    _recompute_totals(inv, lines)
    await session.commit()


# --- state transitions ---------------------------------------------------


async def issue(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Invoice:
    """Lock the invoice, snapshot tax + GST settings, assign a number,
    and flip `status='issued'`. Idempotent: re-issuing returns the row
    unchanged.
    """
    inv = await get_invoice(session, invoice_id)
    if inv.status == InvoiceStatus.issued or inv.status == InvoiceStatus.paid:
        return inv
    if inv.status == InvoiceStatus.void:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot issue a void invoice",
        )

    lines = await _load_lines(session, inv.id)
    if not lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot issue an invoice with no lines",
        )

    settings = await get_org_settings(session, org_id=inv.org_id)
    inv.tax_rate_snapshot = settings.tax_rate
    inv.gst_number = settings.gst_number
    inv.issued_at = datetime.now(timezone.utc)
    inv.status = InvoiceStatus.issued
    inv.number = await _next_invoice_number(session, org_id=inv.org_id)
    _recompute_totals(inv, lines)
    await session.commit()
    await session.refresh(inv)

    await audit.log(
        "billing.invoice_issued",
        entity_type="invoice",
        entity_id=inv.id,
        after={"number": inv.number, "total": str(inv.total)},
        user_id=user_id,
    )
    return inv


async def record_payment(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: PaymentCreate,
) -> Payment:
    inv = await get_invoice(session, invoice_id)
    if inv.status not in (InvoiceStatus.issued, InvoiceStatus.paid):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot record payment against a {inv.status.value} invoice"
            ),
        )

    pay = Payment(
        org_id=inv.org_id,
        invoice_id=inv.id,
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        notes=payload.notes,
    )
    session.add(pay)
    await session.flush()

    paid_so_far = (
        await session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == inv.id
            )
        )
    ).scalar_one()
    paid_so_far = Decimal(paid_so_far)
    if paid_so_far >= inv.total and inv.status != InvoiceStatus.paid:
        inv.status = InvoiceStatus.paid
        inv.paid_at = datetime.now(timezone.utc)
        # Persist the dominant payment method when the invoice closes.
        inv.payment_method = payload.method
    await session.commit()
    await session.refresh(pay)
    await session.refresh(inv)

    await audit.log(
        "billing.payment_recorded",
        entity_type="invoice",
        entity_id=inv.id,
        after={
            "amount": str(pay.amount),
            "method": pay.method.value,
            "paid_so_far": str(paid_so_far),
            "invoice_status": inv.status.value,
        },
        user_id=user_id,
    )
    return pay


async def void(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: Optional[str] = None,
) -> Invoice:
    inv = await get_invoice(session, invoice_id)
    if inv.status == InvoiceStatus.void:
        return inv
    inv.status = InvoiceStatus.void
    if reason:
        inv.notes = (
            f"{inv.notes}\n\n[void] {reason}" if inv.notes else f"[void] {reason}"
        )
    await session.commit()
    await session.refresh(inv)
    await audit.log(
        "billing.invoice_voided",
        entity_type="invoice",
        entity_id=inv.id,
        after={"reason": reason},
        user_id=user_id,
    )
    return inv


# --- helpers --------------------------------------------------------------


async def _load_lines(
    session: AsyncSession, invoice_id: uuid.UUID
) -> list[InvoiceLine]:
    rows = (
        await session.execute(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


def _recompute_totals(inv: Invoice, lines: list[InvoiceLine]) -> None:
    subtotal = sum((ln.line_subtotal for ln in lines), Decimal("0.00"))
    tax = sum((ln.line_total - ln.line_subtotal for ln in lines), Decimal("0.00"))
    discount = inv.discount_amount or Decimal("0.00")
    total = (subtotal + tax - discount).quantize(Decimal("0.01"))
    inv.subtotal = subtotal.quantize(Decimal("0.01"))
    inv.tax_amount = tax.quantize(Decimal("0.01"))
    inv.total = total if total > 0 else Decimal("0.00")


async def _next_invoice_number(
    session: AsyncSession, *, org_id: uuid.UUID
) -> int:
    """Atomically allocate the next per-org invoice number.

    Uses INSERT ... ON CONFLICT DO UPDATE so the row is created on
    first issue, and `RETURNING last_number` gives the freshly
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


__all__ = [
    "add_line",
    "create_draft",
    "delete_invoice",
    "get_invoice",
    "get_invoice_with_lines",
    "issue",
    "list_invoices",
    "list_payments",
    "record_payment",
    "remove_line",
    "update_invoice",
    "void",
]
