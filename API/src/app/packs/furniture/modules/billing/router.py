"""Furniture-pack: POS / quick-checkout HTTP surface.

  POST /api/v1/pos/checkout
    Body: contact phone (+ optional name) · cart lines · payment_method
          · discount.
    Effect — all in one transaction:
      1. Find-or-create the contact (lookup `(org_id, phone)`).
      2. Create a draft invoice, push each cart line.
      3. Issue the invoice (snapshots tax + GST from tbl_org_settings,
         assigns the next per-org invoice number).
      4. Record a single payment for the full total → invoice flips
         to `status='paid'`.
      5. For every line whose `catalog_item_id` maps to inventory at
         the org's default warehouse, dispatch `qty` units.
    Returns the issued + paid invoice plus a `pdf_url`.

Permissions:
  - `pos.use`    → run the checkout
  - `pos.refund` → reserved for the void-after-checkout flow (future)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.billing.models import PaymentMethod
from src.app.core.billing.schemas import (
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceWithLines,
    PaymentCreate,
)
from src.app.core.billing.service import (
    add_line,
    create_draft,
    get_invoice_with_lines,
    record_payment,
)
from src.app.core.billing.service import (
    issue as issue_invoice,
)
from src.app.core.contacts.models import Contact
from src.app.core.users.models import User
from src.app.packs.furniture.modules.inventory.models import (
    InventoryItem,
    MovementType,
    Warehouse,
)
from src.app.packs.furniture.modules.inventory.service import record_movement
from src.app.shared.db import get_db
from src.app.shared.schemas import ORMModel

router = APIRouter(prefix="/pos", tags=["POS"])


# --- request / response schemas -----------------------------------------


class CheckoutLine(BaseModel):
    catalog_item_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=255)
    qty: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0)


class CheckoutPayload(BaseModel):
    contact_phone: str = Field(min_length=3, max_length=32)
    contact_name: str | None = Field(default=None, max_length=255)
    lines: list[CheckoutLine] = Field(min_length=1)
    payment_method: PaymentMethod
    payment_reference: str | None = Field(default=None, max_length=128)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None


class CheckoutResponse(ORMModel):
    invoice: InvoiceWithLines
    pdf_url: str
    inventory_decrements: list[dict[str, Any]] = Field(default_factory=list)


# --- endpoint -----------------------------------------------------------


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def checkout_endpoint(
    payload: CheckoutPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("pos.use")),
) -> CheckoutResponse:
    # 1. Find-or-create contact
    contact = await _find_or_create_contact(
        db,
        org_id=user.org_id,
        phone=payload.contact_phone.strip(),
        name=(payload.contact_name or "Walk-in customer").strip(),
    )

    # 2. Draft invoice with discount applied
    inv = await create_draft(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        payload=InvoiceCreate(
            contact_id=contact.id,
            notes=payload.notes,
        ),
    )
    if payload.discount_amount > 0:
        inv.discount_amount = payload.discount_amount

    # 3. Push lines
    for ln in payload.lines:
        await add_line(
            db,
            invoice_id=inv.id,
            payload=InvoiceLineCreate(
                catalog_item_id=ln.catalog_item_id,
                description=ln.description,
                qty=ln.qty,
                unit_price=ln.unit_price,
            ),
        )

    # 4. Issue (snapshot tax + GST, assign number)
    inv = await issue_invoice(db, invoice_id=inv.id, user_id=user.legacy_uuid)

    # 5. Record a single full-amount payment → flip to `paid`
    await record_payment(
        db,
        invoice_id=inv.id,
        user_id=user.legacy_uuid,
        payload=PaymentCreate(
            amount=inv.total,
            method=payload.payment_method,
            reference=payload.payment_reference,
        ),
    )

    # 6. Inventory decrement for every catalog-linked line.
    decrements: list[dict[str, Any]] = []
    inv, lines = await get_invoice_with_lines(db, inv.id)
    for ln in lines:
        if ln.catalog_item_id is None:
            continue
        inv_item = await _resolve_inventory_item(
            db, org_id=user.org_id, catalog_item_id=ln.catalog_item_id
        )
        if inv_item is None:
            decrements.append(
                {
                    "catalog_item_id": str(ln.catalog_item_id),
                    "skipped": True,
                    "reason": "no inventory row at default warehouse",
                }
            )
            continue
        if inv_item.qty_on_hand < ln.qty:
            # Stock insufficient at the default warehouse — don't fail
            # the checkout (it's already issued + paid), but record
            # the gap so an admin can fix it manually.
            decrements.append(
                {
                    "catalog_item_id": str(ln.catalog_item_id),
                    "item_id": str(inv_item.id),
                    "skipped": True,
                    "reason": (
                        f"insufficient stock: on_hand={inv_item.qty_on_hand}, requested={ln.qty}"
                    ),
                }
            )
            continue
        await record_movement(
            db,
            item_id=inv_item.id,
            user_id=user.legacy_uuid,
            type_=MovementType.dispatch,
            qty=ln.qty,
            reference_type="invoice",
            reference_id=inv.id,
            notes=f"POS sale, invoice #{inv.number}",
        )
        decrements.append(
            {
                "catalog_item_id": str(ln.catalog_item_id),
                "item_id": str(inv_item.id),
                "qty": ln.qty,
            }
        )

    pdf_url = f"/api/v1/invoices/{inv.id}/pdf"
    return CheckoutResponse(
        invoice=InvoiceWithLines(
            **InvoiceOut.model_validate(inv).model_dump(),
            lines=[InvoiceLineOut.model_validate(ln) for ln in lines],
        ),
        pdf_url=pdf_url,
        inventory_decrements=decrements,
    )


# --- helpers ------------------------------------------------------------


async def _find_or_create_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
    name: str,
) -> Contact:
    existing = (
        await session.execute(
            select(Contact).where(Contact.org_id == org_id, Contact.phone == phone)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    new_contact = Contact(
        org_id=org_id,
        full_name=name,
        phone=phone,
        custom_data={},
        tags=[],
        source="walk-in",
    )
    session.add(new_contact)
    await session.flush()
    return new_contact


async def _resolve_inventory_item(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
) -> InventoryItem | None:
    """Resolve catalog → inventory row at the org's default warehouse.

    Falls back to ANY warehouse in the org if no `is_default=True`
    warehouse exists yet, so a fresh demo org with one warehouse
    still works.
    """
    default_stmt = (
        select(InventoryItem)
        .join(Warehouse, Warehouse.id == InventoryItem.warehouse_id)
        .where(
            InventoryItem.catalog_item_id == catalog_item_id,
            Warehouse.org_id == org_id,
            Warehouse.is_default.is_(True),
        )
        .limit(1)
    )
    row = (await session.execute(default_stmt)).scalar_one_or_none()
    if row is not None:
        return row
    fallback_stmt = (
        select(InventoryItem)
        .join(Warehouse, Warehouse.id == InventoryItem.warehouse_id)
        .where(
            InventoryItem.catalog_item_id == catalog_item_id,
            Warehouse.org_id == org_id,
        )
        .limit(1)
    )
    return (await session.execute(fallback_stmt)).scalar_one_or_none()
