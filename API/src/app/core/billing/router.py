"""HTTP routes for core billing.

  /api/v1/invoices                       (CRUD + filters)
  /api/v1/invoices/{id}/lines            (POST add, DELETE remove)
  /api/v1/invoices/{id}/issue            (POST)
  /api/v1/invoices/{id}/void             (POST)
  /api/v1/invoices/{id}/payments         (GET, POST)
  /api/v1/invoices/{id}/pdf              (GET — uses pack-registered renderer)

Permissions:
  - `billing.read`   → all GETs
  - `billing.write`  → create / update / delete / lines / issue / payments
  - `billing.refund` → void
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.billing import pdf_registry
from src.app.core.billing.models import InvoiceStatus
from src.app.core.billing.schemas import (
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceLineOut,
    InvoiceListResponse,
    InvoiceOut,
    InvoiceUpdate,
    InvoiceWithLines,
    PaymentCreate,
    PaymentOut,
)
from src.app.core.billing.service import (
    add_line,
    create_draft,
    delete_invoice,
    get_invoice,
    get_invoice_with_lines,
    issue,
    list_invoices,
    list_payments,
    record_payment,
    remove_line,
    update_invoice,
    void as void_invoice,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/invoices", tags=["Billing"])


# --- list / get -----------------------------------------------------------


@router.get("", response_model=InvoiceListResponse)
async def list_invoices_endpoint(
    status_: Optional[InvoiceStatus] = Query(default=None, alias="status"),
    contact_id: Optional[uuid.UUID] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.read")),
) -> InvoiceListResponse:
    rows, total = await list_invoices(
        db,
        status_filter=status_,
        contact_id=contact_id,
        page=page,
        size=size,
    )
    return InvoiceListResponse(
        items=[InvoiceOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice_endpoint(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("billing.write")),
) -> InvoiceOut:
    inv = await create_draft(db, org_id=user.org_id, user_id=user.legacy_uuid, payload=payload)
    return InvoiceOut.model_validate(inv)


@router.get("/{invoice_id}", response_model=InvoiceWithLines)
async def get_invoice_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.read")),
) -> InvoiceWithLines:
    inv, lines = await get_invoice_with_lines(db, invoice_id)
    return InvoiceWithLines(
        **InvoiceOut.model_validate(inv).model_dump(),
        lines=[InvoiceLineOut.model_validate(ln) for ln in lines],
    )


@router.patch("/{invoice_id}", response_model=InvoiceOut)
async def update_invoice_endpoint(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.write")),
) -> InvoiceOut:
    inv = await update_invoice(db, invoice_id=invoice_id, payload=payload)
    return InvoiceOut.model_validate(inv)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.write")),
) -> Response:
    await delete_invoice(db, invoice_id=invoice_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- lines ----------------------------------------------------------------


@router.post(
    "/{invoice_id}/lines",
    response_model=InvoiceLineOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_line_endpoint(
    invoice_id: uuid.UUID,
    payload: InvoiceLineCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.write")),
) -> InvoiceLineOut:
    line = await add_line(db, invoice_id=invoice_id, payload=payload)
    return InvoiceLineOut.model_validate(line)


@router.delete(
    "/{invoice_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_line_endpoint(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.write")),
) -> Response:
    await remove_line(db, invoice_id=invoice_id, line_id=line_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- state transitions ---------------------------------------------------


@router.post("/{invoice_id}/issue", response_model=InvoiceOut)
async def issue_invoice_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("billing.write")),
) -> InvoiceOut:
    inv = await issue(db, invoice_id=invoice_id, user_id=user.legacy_uuid)
    return InvoiceOut.model_validate(inv)


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("billing.refund")),
) -> InvoiceOut:
    inv = await void_invoice(db, invoice_id=invoice_id, user_id=user.legacy_uuid)
    return InvoiceOut.model_validate(inv)


# --- payments ------------------------------------------------------------


@router.get(
    "/{invoice_id}/payments", response_model=list[PaymentOut]
)
async def list_payments_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.read")),
) -> list[PaymentOut]:
    await get_invoice(db, invoice_id)
    rows = await list_payments(db, invoice_id=invoice_id)
    return [PaymentOut.model_validate(r) for r in rows]


@router.post(
    "/{invoice_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_payment_endpoint(
    invoice_id: uuid.UUID,
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("billing.write")),
) -> PaymentOut:
    pay = await record_payment(
        db, invoice_id=invoice_id, user_id=user.legacy_uuid, payload=payload
    )
    return PaymentOut.model_validate(pay)


# --- PDF (uses pack-registered renderer) --------------------------------


@router.get("/{invoice_id}/pdf")
async def invoice_pdf_endpoint(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("billing.read")),
) -> Response:
    renderer = pdf_registry.get_renderer()
    if renderer is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "No PDF renderer is registered. Install a vertical pack "
                "(e.g. furniture) that registers one."
            ),
        )
    inv, lines = await get_invoice_with_lines(db, invoice_id)
    org_meta = {
        "gst_number": inv.gst_number,
        "currency": inv.currency,
    }
    data, filename = await renderer(inv, lines, org_meta)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
