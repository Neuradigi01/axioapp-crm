"""`invoice.paid` and `invoice.finalized` handlers.

Both events flow into the same `subscription_invoices` upsert keyed by
`stripe_invoice_id`. The status on the row reflects the event:
  - `invoice.paid` → `status='paid'`, `paid_at` filled.
  - `invoice.finalized` → status taken straight from the event's
    payload (commonly `open`).

`invoice.paid` additionally resumes a `past_due` subscription back to
`active` — the customer's card succeeded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions.models import (
    Subscription,
    SubscriptionInvoice,
)
from src.app.core.subscriptions.webhooks.handlers import (
    find_subscription_by_stripe_id,
    parse_unix_ts,
)

log = logging.getLogger(__name__)


# Stripe-side statuses we accept on `subscription_invoices`. Anything
# else gets mapped to `open` so the CHECK constraint doesn't trip.
_KNOWN_INVOICE_STATUSES = frozenset(
    {"paid", "open", "void", "uncollectible", "draft"}
)


async def on_invoice_paid(
    db: AsyncSession, event: dict[str, Any],
) -> None:
    invoice = event.get("data", {}).get("object", {}) or {}
    sub = await _upsert_invoice(db, invoice, force_status="paid")
    if sub is None:
        return

    # If the customer's previous invoice failed, the sub may be in
    # `past_due`; a successful payment moves it back to `active`. The
    # conditional UPDATE makes this a no-op if status is already
    # something else (e.g. `cancelled` after a delayed event).
    result = await db.execute(
        update(Subscription)
        .where(
            Subscription.id == sub.id,
            Subscription.status == "past_due",
        )
        .values(status="active")
    )
    await db.commit()
    if (result.rowcount or 0) > 0:
        await audit.log(
            "payment.succeeded",
            org_id=sub.org_id,
            entity_type="subscription",
            entity_id=sub.id,
            before={"status": "past_due"},
            after={"status": "active"},
            user_id=None,
        )
        log.info(
            "invoice.paid → org %s resumed from past_due to active",
            sub.org_id,
        )


async def on_invoice_finalized(
    db: AsyncSession, event: dict[str, Any],
) -> None:
    invoice = event.get("data", {}).get("object", {}) or {}
    await _upsert_invoice(db, invoice)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _upsert_invoice(
    db: AsyncSession,
    invoice: dict[str, Any],
    *,
    force_status: str | None = None,
) -> Subscription | None:
    """Upsert a `subscription_invoices` row from a Stripe invoice dict.

    Returns the linked `Subscription` for the caller's follow-up work
    (`on_invoice_paid` flips status; `on_invoice_failed` likewise),
    or `None` when the upsert was skipped because no local sub matches.
    """
    stripe_invoice_id = invoice.get("id")
    if not stripe_invoice_id:
        raise ValueError("invoice event missing `id`")

    stripe_sub_id = invoice.get("subscription")
    sub = await find_subscription_by_stripe_id(db, stripe_sub_id)
    if sub is None:
        # Out-of-order or one-off invoice (e.g. an account credit).
        # We can't FK-link without a subscription, so raise and let
        # Stripe retry — the checkout handler usually catches up
        # within seconds.
        raise ValueError(
            f"No local subscription matches stripe_subscription_id "
            f"{stripe_sub_id!r}; deferring invoice upsert."
        )

    status_raw = (
        force_status
        if force_status is not None
        else invoice.get("status") or "open"
    )
    status = status_raw if status_raw in _KNOWN_INVOICE_STATUSES else "open"

    paid_at: datetime | None = None
    if status == "paid":
        transitions = invoice.get("status_transitions") or {}
        paid_at = (
            parse_unix_ts(transitions.get("paid_at"))
            or datetime.now(tz=timezone.utc)
        )

    currency = (invoice.get("currency") or "usd").upper()

    insert_stmt = (
        pg_insert(SubscriptionInvoice)
        .values(
            org_id=sub.org_id,
            subscription_id=sub.id,
            stripe_invoice_id=stripe_invoice_id,
            number=invoice.get("number"),
            status=status,
            amount_due_cents=int(invoice.get("amount_due") or 0),
            amount_paid_cents=int(invoice.get("amount_paid") or 0),
            currency=currency,
            period_start=parse_unix_ts(invoice.get("period_start")),
            period_end=parse_unix_ts(invoice.get("period_end")),
            hosted_invoice_url=invoice.get("hosted_invoice_url"),
            pdf_url=invoice.get("invoice_pdf"),
            paid_at=paid_at,
        )
        .on_conflict_do_update(
            index_elements=["stripe_invoice_id"],
            set_={
                "status": status,
                "number": invoice.get("number"),
                "amount_paid_cents": int(invoice.get("amount_paid") or 0),
                "hosted_invoice_url": invoice.get("hosted_invoice_url"),
                "pdf_url": invoice.get("invoice_pdf"),
                "paid_at": paid_at,
            },
        )
    )
    await db.execute(insert_stmt)
    await db.commit()
    return sub
