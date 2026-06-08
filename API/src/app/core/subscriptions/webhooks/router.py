"""Stripe webhook ingress — Step 13.a.

This file ships the *frame* of webhook handling: signature
verification, dedup ledger via `INSERT … ON CONFLICT DO NOTHING`,
and an empty dispatch table. Sub-step 13.b populates the dispatch
with the real handlers (checkout, invoice, subscription).

Contract:

  - Returns 200 on a verified event (whether duplicate, newly-processed,
    or a no-op event type we don't care about).
  - Returns 400 when signature verification fails or the event lacks
    an `id`.
  - Returns 500 when a handler raises — the ledger row's `error`
    column is populated and `processed_at` stays NULL so Stripe's
    retry re-runs the handler.
  - Returns 503 when the Stripe provider is unconfigured (no
    `STRIPE_SECRET_KEY`) — the endpoint should not be exposed in that
    deployment; document the runbook.

The endpoint is **unauthenticated** — Stripe signs the body and we
verify the signature instead of accepting a JWT. The subscription
state middleware (Step 10) does not block this path because POST on
an unauthenticated path has no `ctx.org_id` to gate against.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.subscriptions.dependencies import get_payment_provider
from src.app.core.subscriptions.models import StripeWebhookEvent
from src.app.core.subscriptions.payment_provider import PaymentProvider
from src.app.core.subscriptions.providers.stripe_provider import (
    InvalidWebhookSignature,
)
from src.app.shared.db import get_db

log = logging.getLogger(__name__)


router = APIRouter(tags=["Stripe Webhooks"])


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payment_provider: PaymentProvider | None = Depends(get_payment_provider),
) -> dict[str, Any]:
    """Receive a Stripe-signed event.

    Order is: verify → dedup → dispatch → mark processed. Failure at
    any point leaves a useful row in `stripe_webhook_events` for the
    operator to inspect.
    """
    if payment_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "payment_provider_unavailable"},
        )

    body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = await payment_provider.verify_webhook(body, signature)
    except InvalidWebhookSignature:
        # Never leak SDK error text — that would tune a forged-
        # signature attack. The Step 11 provider already logs the
        # underlying reason at WARN.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_signature"},
        )

    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_event_id"},
        )

    now = datetime.now(tz=timezone.utc)

    # Dedup: insert the ledger row; ON CONFLICT means we've seen this
    # event ID before. The "before" might be still-in-flight (race
    # between Stripe's retry and our first handler) or fully
    # processed. Either way, 200 + idempotent skip is correct.
    insert_stmt = (
        pg_insert(StripeWebhookEvent)
        .values(
            stripe_event_id=event_id,
            event_type=event_type,
            received_at=now,
            payload=event,
        )
        .on_conflict_do_nothing(index_elements=["stripe_event_id"])
    )
    result = await db.execute(insert_stmt)
    await db.commit()

    if (result.rowcount or 0) == 0:
        log.info(
            "Stripe webhook event %s (%s) deduped — already in ledger",
            event_id, event_type,
        )
        return {"received": True, "duplicate": True}

    # Dispatch. Sub-step 13.a ships an empty table — every event type
    # routes to `_no_op` which logs and returns. 13.b extends this.
    try:
        await _dispatch(db, event_type, event)
    except Exception as exc:  # noqa: BLE001 — handler error surface
        log.exception(
            "Stripe webhook handler raised for event %s (%s)",
            event_id, event_type,
        )
        # Persist the error on the ledger row so the operator has a
        # clue without re-running. `processed_at` stays NULL so a
        # future replay can re-dispatch.
        await db.execute(
            update(StripeWebhookEvent)
            .where(StripeWebhookEvent.stripe_event_id == event_id)
            .values(error=str(exc)[:2000])
        )
        await db.commit()
        # 500 so Stripe retries on its own cadence.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "handler_failed"},
        )

    await db.execute(
        update(StripeWebhookEvent)
        .where(StripeWebhookEvent.stripe_event_id == event_id)
        .values(processed_at=datetime.now(tz=timezone.utc))
    )
    await db.commit()
    return {"received": True, "duplicate": False, "type": event_type}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _no_op(
    db: AsyncSession,  # noqa: ARG001
    event: dict[str, Any],
) -> None:
    """Default handler for sub-step 13.a — logs and returns.

    Sub-step 13.b replaces the entries in `_HANDLERS` with real
    functions, leaving `_no_op` as the fallback for unknown event
    types so we don't 5xx on unrelated Stripe traffic (e.g. account
    health-check pings).
    """
    log.info(
        "Stripe webhook event %r received (no-op handler)",
        event.get("type"),
    )


# Mapping event type → async handler. Sub-step 13.b extends this.
# Keeping the table at module scope lets tests assert on it and lets
# the future handlers import it cleanly.
_HANDLERS: dict[str, Any] = {
    # "checkout.session.completed": on_checkout_completed,  # 13.b
    # "invoice.paid": on_invoice_paid,                      # 13.b
    # "invoice.payment_failed": on_invoice_failed,          # 13.b
    # "invoice.finalized": on_invoice_finalized,            # 13.b
    # "customer.subscription.updated": on_subscription_updated,    # 13.b
    # "customer.subscription.deleted": on_subscription_cancelled,  # 13.b
}


async def _dispatch(
    db: AsyncSession, event_type: str, event: dict[str, Any],
) -> None:
    handler = _HANDLERS.get(event_type, _no_op)
    await handler(db, event)
