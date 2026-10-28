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
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.billing import data_access as _da
from src.app.core.billing.models import (
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
)
from src.app.core.billing.schemas import (
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceUpdate,
    PaymentCreate,
)
from src.app.core.settings.service import get_or_create as get_org_settings
from src.app.shared.db.queries import ensure_found

# --- reads ----------------------------------------------------------------


async def list_invoices(
    session: AsyncSession,
    *,
    status_filter: InvoiceStatus | None = None,
    contact_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Invoice], int]:
    return await _da.list_invoices_query(
        session,
        status_filter=status_filter,
        contact_id=contact_id,
        page=page,
        size=size,
    )


async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    return ensure_found(await _da.get_invoice_by_id(session, invoice_id), entity="invoice")


async def get_invoice_with_lines(
    session: AsyncSession, invoice_id: uuid.UUID
) -> tuple[Invoice, list[InvoiceLine]]:
    invoice = await get_invoice(session, invoice_id)
    lines = await _da.list_invoice_lines(session, invoice.id)
    return invoice, lines


async def list_payments(session: AsyncSession, *, invoice_id: uuid.UUID) -> list[Payment]:
    return await _da.list_payments_query(session, invoice_id=invoice_id)


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
    _da.insert_invoice(session, inv)
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
            detail=(f"invoice {inv.id} is {inv.status.value}, only drafts are editable"),
        )
    changed = False
    for field in ("contact_id", "discount_amount", "notes", "custom_data"):
        v = getattr(payload, field)
        if v is not None:
            setattr(inv, field, v)
            changed = True
    if changed:
        _recompute_totals(inv, await _da.list_invoice_lines(session, inv.id))
        await session.commit()
        await session.refresh(inv)
    return inv


async def delete_invoice(session: AsyncSession, *, invoice_id: uuid.UUID) -> None:
    inv = await get_invoice(session, invoice_id)
    if inv.status != InvoiceStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only draft invoices can be deleted; void issued ones instead",
        )
    await _da.delete_invoice_row(session, inv)
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
    _da.insert_invoice_line(session, line)
    await session.flush()

    lines = await _da.list_invoice_lines(session, inv.id)
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
    line = ensure_found(
        await _da.get_invoice_line(session, invoice_id=invoice_id, line_id=line_id),
        entity="line",
    )
    await _da.delete_invoice_line(session, line)
    await session.flush()
    lines = await _da.list_invoice_lines(session, inv.id)
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

    lines = await _da.list_invoice_lines(session, inv.id)
    if not lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot issue an invoice with no lines",
        )

    settings = await get_org_settings(session, org_id=inv.org_id)
    inv.tax_rate_snapshot = settings.tax_rate
    inv.gst_number = settings.gst_number
    inv.issued_at = datetime.now(UTC)
    inv.status = InvoiceStatus.issued
    inv.number = await _da.next_invoice_number(session, org_id=inv.org_id)
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

    # tasks/automation-engine Step 11 — publish ``invoice.sent`` so
    # the seeded "Invoice Sent" trigger fires the customer email.
    # After-commit so a publish failure can't roll back the issue.
    await _publish_invoice_event(
        session=session,
        inv=inv,
        event_type="invoice.sent",
        event_id_prefix="invoice_sent",
        extra=None,
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
            detail=(f"cannot record payment against a {inv.status.value} invoice"),
        )

    pay = Payment(
        org_id=inv.org_id,
        invoice_id=inv.id,
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        notes=payload.notes,
    )
    _da.insert_payment(session, pay)
    await session.flush()

    paid_so_far = await _da.sum_payments(session, inv.id)
    flipped_to_paid = False
    if paid_so_far >= inv.total and inv.status != InvoiceStatus.paid:
        inv.status = InvoiceStatus.paid
        inv.paid_at = datetime.now(UTC)
        # Persist the dominant payment method when the invoice closes.
        inv.payment_method = payload.method
        flipped_to_paid = True
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

    # tasks/automation-engine Step 11 — publish ``invoice.paid`` once
    # the cumulative payment sum closes the invoice. The
    # ``flipped_to_paid`` gate ensures a partial-payment record
    # doesn't fire the event; the deterministic ``event_id`` absorbs
    # any belt-and-braces double-call by the operator.
    if flipped_to_paid:
        await _publish_invoice_event(
            session=session,
            inv=inv,
            event_type="invoice.paid",
            event_id_prefix="invoice_paid",
            extra={
                "paid_at": (inv.paid_at.isoformat() if inv.paid_at else None),
                "payment_method": (inv.payment_method.value if inv.payment_method else None),
            },
        )

    return pay


async def void(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str | None = None,
) -> Invoice:
    inv = await get_invoice(session, invoice_id)
    if inv.status == InvoiceStatus.void:
        return inv
    inv.status = InvoiceStatus.void
    if reason:
        inv.notes = f"{inv.notes}\n\n[void] {reason}" if inv.notes else f"[void] {reason}"
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


def _recompute_totals(inv: Invoice, lines: list[InvoiceLine]) -> None:
    subtotal = sum((ln.line_subtotal for ln in lines), Decimal("0.00"))
    tax = sum((ln.line_total - ln.line_subtotal for ln in lines), Decimal("0.00"))
    discount = inv.discount_amount or Decimal("0.00")
    total = (subtotal + tax - discount).quantize(Decimal("0.01"))
    inv.subtotal = subtotal.quantize(Decimal("0.01"))
    inv.tax_amount = tax.quantize(Decimal("0.01"))
    inv.total = total if total > 0 else Decimal("0.00")


# --- Step-11 event publisher ---------------------------------------------


async def _publish_invoice_event(
    *,
    session: AsyncSession,
    inv: Invoice,
    event_type: str,
    event_id_prefix: str,
    extra: dict | None,
) -> None:
    """Build the ``invoice.*`` envelope + publish via the bus.

    Hydrates Contact + Organization so the recipient resolver +
    template renderer have everything they need at dispatch time
    without a per-handler DB hit. Mirrors the Step 5/6/10
    ``_publish_*`` helpers: try/except wrapper around the entire body
    so a misbehaving subscriber + a missing bus module can never roll
    back the freshly-committed billing write.

    The ``extra`` dict folds into the top-level payload + the
    nested ``invoice`` dict — used for the ``paid_at`` /
    ``payment_method`` keys that only ``invoice.paid`` carries.
    """
    try:
        from sqlalchemy import select as _select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        contact = None
        if inv.contact_id is not None:
            contact = (
                await session.execute(_select(Contact).where(Contact.id == inv.contact_id))
            ).scalar_one_or_none()
        org = (
            await session.execute(_select(Organization).where(Organization.id == inv.org_id))
        ).scalar_one_or_none()

        payload: dict = {
            "invoice_id": str(inv.id),
            "contact_id": (str(inv.contact_id) if inv.contact_id else None),
            "total_amount": str(inv.total),
            "currency": inv.currency,
            "invoice": {
                "id": str(inv.id),
                "number": inv.number,
                "total_amount": str(inv.total),
                "currency": inv.currency,
                "issued_at": (inv.issued_at.isoformat() if inv.issued_at else None),
            },
        }
        if extra:
            payload.update(extra)
            # Mirror the extras into the nested invoice dict so the
            # template renderer can use either path
            # (`{{ paid_at }}` OR `{{ invoice.paid_at }}`).
            payload["invoice"].update(extra)

        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        await events_publish(
            event_type,
            payload,
            org_id=inv.org_id,
            event_id=f"{event_id_prefix}:{inv.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "billing publish_invoice_event_failed org=%s invoice=%s event=%s",
            inv.org_id,
            inv.id,
            event_type,
        )


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
