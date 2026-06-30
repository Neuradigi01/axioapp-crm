"""Tests for the Step 13.b Stripe webhook handlers.

Each test calls the handler directly with a hand-crafted event dict
and a real `TestSession`, then asserts the resulting DB state. The
dedup ledger and signature verification are out of scope here —
that's Step 13.a's `test_subscriptions_webhook_dedup.py`.

The handlers' contracts:
  - Success → DB updated, audit row written.
  - Idempotent → calling twice does not duplicate rows or double-emit
    audit beyond what the conditional UPDATEs allow.
  - Missing local state → raise (the router converts to 500 → Stripe
    retries).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.app.core.audit.models import AuditLog
from src.app.core.subscriptions.models import (
    Subscription,
    SubscriptionInvoice,
)
from src.app.core.subscriptions.webhooks.handlers.checkout_completed import (
    on_checkout_completed,
)
from src.app.core.subscriptions.webhooks.handlers.invoice_failed import (
    on_invoice_failed,
)
from src.app.core.subscriptions.webhooks.handlers.invoice_paid import (
    on_invoice_finalized,
    on_invoice_paid,
)
from src.app.core.subscriptions.webhooks.handlers.subscription_cancelled import (
    on_subscription_cancelled,
)
from src.app.core.subscriptions.webhooks.handlers.subscription_updated import (
    on_subscription_updated,
)
from src.app.core.subscriptions.webhooks.router import _HANDLERS
from src.app.core.tenants.models import Organization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_org_with_sub(
    test_db,
    *,
    plan_code: str = "trial",
    status: str = "trialing",
    billing_cycle: str = "monthly",
    seats_purchased: int = 3,
    stripe_subscription_id: str | None = None,
    pending_checkout_session_id: str | None = None,
    stripe_customer_id: str | None = None,
) -> tuple[Organization, Subscription]:
    org = Organization(
        id=uuid.uuid4(),
        name="Webhook Co",
        slug=f"wh-{uuid.uuid4().hex[:6]}",
    )
    test_db.add(org)
    await test_db.flush()

    now = datetime.now(tz=UTC)
    sub = Subscription(
        org_id=org.id,
        plan_code=plan_code,
        status=status,
        billing_cycle=billing_cycle,
        seats_purchased=seats_purchased,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
        pending_checkout_session_id=pending_checkout_session_id,
    )
    test_db.add(sub)
    await test_db.commit()
    await test_db.refresh(sub)
    return org, sub


def _checkout_completed_event(
    org_id: uuid.UUID,
    *,
    plan_code: str = "standard",
    billing_cycle: str = "monthly",
    seats: int = 5,
    session_id: str = "cs_test_abc",
    subscription: str = "sub_stripe_xyz",
    customer: str = "cus_test_123",
) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "subscription": subscription,
                "customer": customer,
                "metadata": {
                    "org_id": str(org_id),
                    "plan_code": plan_code,
                    "billing_cycle": billing_cycle,
                    "seats": str(seats),
                },
            },
        },
    }


def _invoice_event(
    *,
    event_type: str,
    subscription: str,
    invoice_id: str = "in_test_1",
    status: str = "paid",
    amount_due: int = 6000,
    amount_paid: int | None = None,
    number: str = "INV-001",
    paid_at_ts: int | None = None,
) -> dict:
    if amount_paid is None:
        amount_paid = amount_due if status == "paid" else 0
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "data": {
            "object": {
                "id": invoice_id,
                "subscription": subscription,
                "customer": "cus_test_123",
                "status": status,
                "amount_due": amount_due,
                "amount_paid": amount_paid,
                "currency": "usd",
                "number": number,
                "period_start": 1700000000,
                "period_end": 1702592000,
                "hosted_invoice_url": "https://invoice.stripe.com/i/test",
                "invoice_pdf": "https://pay.stripe.com/test/pdf",
                "status_transitions": ({"paid_at": paid_at_ts} if paid_at_ts is not None else {}),
            },
        },
    }


def _subscription_updated_event(
    stripe_sub_id: str,
    *,
    quantity: int = 8,
    plan_code: str | None = "standard",
    billing_cycle: str | None = "monthly",
) -> dict:
    price: dict = {"id": "price_test"}
    metadata: dict = {}
    if plan_code:
        metadata["plan_code"] = plan_code
    if billing_cycle:
        metadata["billing_cycle"] = billing_cycle
    price["metadata"] = metadata
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": stripe_sub_id,
                "items": {
                    "data": [
                        {
                            "id": "si_test",
                            "quantity": quantity,
                            "price": price,
                        },
                    ],
                },
            },
        },
    }


def _subscription_deleted_event(stripe_sub_id: str) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": stripe_sub_id, "status": "canceled"}},
    }


# ---------------------------------------------------------------------------
# Dispatch wiring
# ---------------------------------------------------------------------------


def test_dispatch_table_wires_all_six_event_types():
    """Sanity check that the router's `_HANDLERS` table covers the
    full set defined in the spec — guards against a handler being
    added in this file but forgotten in the dispatch import."""
    assert set(_HANDLERS) == {
        "checkout.session.completed",
        "invoice.paid",
        "invoice.finalized",
        "invoice.payment_failed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_flips_subscription(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="trial",
        status="trialing",
        seats_purchased=3,
        pending_checkout_session_id="cs_test_abc",
    )
    event = _checkout_completed_event(
        org.id,
        plan_code="standard",
        billing_cycle="annual",
        seats=5,
        session_id="cs_test_abc",
        subscription="sub_stripe_xyz",
        customer="cus_test_123",
    )

    await on_checkout_completed(test_db, event)

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.status == "active"
    assert fresh.plan_code == "standard"
    assert fresh.billing_cycle == "annual"
    assert fresh.seats_purchased == 5
    assert fresh.stripe_subscription_id == "sub_stripe_xyz"
    assert fresh.stripe_customer_id == "cus_test_123"
    assert fresh.pending_checkout_session_id is None


@pytest.mark.asyncio
async def test_checkout_completed_missing_metadata_raises(test_db):
    org, _ = await _seed_org_with_sub(test_db)
    bad_event = {
        "id": "evt_x",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"org_id": str(org.id)}}},
    }
    with pytest.raises(ValueError):
        await on_checkout_completed(test_db, bad_event)


@pytest.mark.asyncio
async def test_checkout_completed_is_idempotent(test_db):
    org, sub = await _seed_org_with_sub(test_db, plan_code="trial")
    event = _checkout_completed_event(
        org.id,
        plan_code="basic",
        billing_cycle="monthly",
        seats=5,
    )

    await on_checkout_completed(test_db, event)
    await on_checkout_completed(test_db, event)

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.plan_code == "basic"
    assert fresh.status == "active"


# ---------------------------------------------------------------------------
# invoice.paid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_paid_upserts_row_and_resumes_past_due(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="basic",
        status="past_due",
        stripe_subscription_id="sub_test_99",
    )
    event = _invoice_event(
        event_type="invoice.paid",
        subscription="sub_test_99",
        invoice_id="in_99",
        status="paid",
        amount_due=6000,
        amount_paid=6000,
        paid_at_ts=1701000000,
    )

    await on_invoice_paid(test_db, event)

    # Invoice row created with status=paid.
    inv = (
        await test_db.execute(
            select(SubscriptionInvoice).where(SubscriptionInvoice.stripe_invoice_id == "in_99")
        )
    ).scalar_one()
    assert inv.status == "paid"
    assert inv.amount_paid_cents == 6000
    assert inv.paid_at is not None

    # past_due resumed to active.
    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.status == "active"


@pytest.mark.asyncio
async def test_invoice_paid_is_idempotent_single_invoice_row(test_db):
    org, _ = await _seed_org_with_sub(
        test_db,
        status="active",
        stripe_subscription_id="sub_x",
    )
    event = _invoice_event(
        event_type="invoice.paid",
        subscription="sub_x",
        invoice_id="in_idem",
    )

    await on_invoice_paid(test_db, event)
    await on_invoice_paid(test_db, event)

    rows = (
        (
            await test_db.execute(
                select(SubscriptionInvoice).where(
                    SubscriptionInvoice.stripe_invoice_id == "in_idem"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_invoice_finalized_inserts_open_invoice(test_db):
    org, _ = await _seed_org_with_sub(
        test_db,
        status="active",
        stripe_subscription_id="sub_fin",
    )
    event = _invoice_event(
        event_type="invoice.finalized",
        subscription="sub_fin",
        invoice_id="in_fin",
        status="open",
        amount_due=14500,
        amount_paid=0,
    )

    await on_invoice_finalized(test_db, event)

    inv = (
        await test_db.execute(
            select(SubscriptionInvoice).where(SubscriptionInvoice.stripe_invoice_id == "in_fin")
        )
    ).scalar_one()
    assert inv.status == "open"
    assert inv.paid_at is None


@pytest.mark.asyncio
async def test_invoice_paid_raises_when_subscription_unknown(test_db):
    event = _invoice_event(
        event_type="invoice.paid",
        subscription="sub_unknown",
        invoice_id="in_orphan",
    )
    with pytest.raises(ValueError):
        await on_invoice_paid(test_db, event)


# ---------------------------------------------------------------------------
# invoice.payment_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_failed_flips_active_to_past_due(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="basic",
        status="active",
        stripe_subscription_id="sub_pf",
    )
    event = _invoice_event(
        event_type="invoice.payment_failed",
        subscription="sub_pf",
        invoice_id="in_pf",
        status="open",
        amount_due=6000,
        amount_paid=0,
    )

    await on_invoice_failed(test_db, event)

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.status == "past_due"


# ---------------------------------------------------------------------------
# customer.subscription.updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_updated_syncs_quantity(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="standard",
        status="active",
        seats_purchased=5,
        stripe_subscription_id="sub_q",
    )
    event = _subscription_updated_event(
        "sub_q",
        quantity=8,
        plan_code="standard",
        billing_cycle="monthly",
    )

    await on_subscription_updated(test_db, event)

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.seats_purchased == 8


@pytest.mark.asyncio
async def test_subscription_updated_unknown_sub_is_silent_noop(test_db):
    """Stripe-side cleanup of an unlinked sub should not raise — the
    dedup ledger still records the event so Stripe stops retrying."""
    event = _subscription_updated_event("sub_unlinked")
    # Should not raise.
    await on_subscription_updated(test_db, event)


# ---------------------------------------------------------------------------
# customer.subscription.deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_deleted_cancels_local_row(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="basic",
        status="active",
        stripe_subscription_id="sub_del",
    )

    event = _subscription_deleted_event("sub_del")
    await on_subscription_cancelled(test_db, event)

    fresh = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(fresh)
    assert fresh.status == "cancelled"
    assert fresh.cancelled_at is not None


@pytest.mark.asyncio
async def test_subscription_deleted_is_idempotent(test_db):
    org, sub = await _seed_org_with_sub(
        test_db,
        plan_code="basic",
        status="active",
        stripe_subscription_id="sub_del2",
    )

    event = _subscription_deleted_event("sub_del2")
    await on_subscription_cancelled(test_db, event)
    # First cancellation timestamp must be preserved on the second call.
    first = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(first)
    first_cancelled_at = first.cancelled_at

    await on_subscription_cancelled(test_db, event)

    second = (
        await test_db.execute(select(Subscription).where(Subscription.id == sub.id))
    ).scalar_one()
    await test_db.refresh(second)
    assert second.status == "cancelled"
    assert second.cancelled_at == first_cancelled_at


# ---------------------------------------------------------------------------
# Audit events fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_event_written_for_checkout_completed(test_db):
    org, sub = await _seed_org_with_sub(test_db, plan_code="trial")
    event = _checkout_completed_event(
        org.id,
        plan_code="basic",
        billing_cycle="monthly",
        seats=5,
    )
    await on_checkout_completed(test_db, event)

    rows = (
        (
            await test_db.execute(
                select(AuditLog).where(
                    AuditLog.action == "subscription.upgraded",
                    AuditLog.entity_id == sub.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1
