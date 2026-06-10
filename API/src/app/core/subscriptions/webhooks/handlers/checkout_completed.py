"""`checkout.session.completed` handler.

Fires when a user finishes paying on Stripe-hosted Checkout. Applies
the requested plan / cycle / seats to the local subscription, links
the Stripe subscription ID, and clears `pending_checkout_session_id`.

Idempotency
-----------
The Step 13.a dedup ledger short-circuits redelivery before this
handler runs, so a second arrival of the same `evt_…` never reaches
here. Within a single arrival, the conditional UPDATE simply re-
asserts the target state — no-op on already-correct rows.

Failure modes
-------------
Raises if:
  - the event payload omits `metadata.org_id` / `metadata.plan_code`
    / `metadata.billing_cycle` / `metadata.seats` — these are set by
    Step 11's `StripeProvider.create_checkout_session`, so missing
    keys mean we shipped Checkout with a different code path.
  - the org has no subscription row at all — should not happen post
    the Step 2 backfill, but we'd rather 500 + retry than silently
    create a row from an arbitrary webhook.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions import plans
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.notifications import send_billing_email

log = logging.getLogger(__name__)


async def on_checkout_completed(
    db: AsyncSession, event: dict[str, Any],
) -> None:
    session_obj = event.get("data", {}).get("object", {}) or {}
    metadata = session_obj.get("metadata") or {}

    org_id_raw = metadata.get("org_id")
    plan_code = metadata.get("plan_code")
    billing_cycle = metadata.get("billing_cycle")
    seats_raw = metadata.get("seats")
    if not (org_id_raw and plan_code and billing_cycle and seats_raw):
        raise ValueError(
            "checkout.session.completed payload missing required metadata "
            "(org_id / plan_code / billing_cycle / seats). The Step 11 "
            "provider sets all four; missing keys mean an upstream change."
        )

    try:
        org_id = uuid.UUID(org_id_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"checkout.session.completed metadata.org_id is not a UUID: "
            f"{org_id_raw!r}"
        ) from exc
    seats = int(seats_raw)
    stripe_subscription_id = session_obj.get("subscription")
    stripe_customer_id = session_obj.get("customer")

    # Find the org's most-recent subscription regardless of status;
    # this covers the case of an org that had a `cancelled` row and is
    # paying again from the public pricing page.
    sub = (
        await db.execute(
            select(Subscription)
            .where(Subscription.org_id == org_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise ValueError(
            f"No subscription row for org {org_id} — cannot apply "
            "checkout.session.completed."
        )

    before = {
        "status": sub.status,
        "plan_code": sub.plan_code,
        "billing_cycle": sub.billing_cycle,
        "seats_purchased": sub.seats_purchased,
    }

    values: dict[str, Any] = {
        "status": "active",
        "plan_code": plan_code,
        "billing_cycle": billing_cycle,
        "seats_purchased": seats,
        "pending_checkout_session_id": None,
    }
    if stripe_subscription_id:
        values["stripe_subscription_id"] = stripe_subscription_id
    if stripe_customer_id and not sub.stripe_customer_id:
        values["stripe_customer_id"] = stripe_customer_id

    await db.execute(
        update(Subscription).where(Subscription.id == sub.id).values(**values)
    )
    await db.commit()

    await audit.log(
        "subscription.upgraded",
        org_id=org_id,
        entity_type="subscription",
        entity_id=sub.id,
        before=before,
        after={
            "status": "active",
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "seats_purchased": seats,
            "stripe_subscription_id": stripe_subscription_id,
        },
        user_id=None,
    )
    log.info(
        "Stripe Checkout completed → org %s flipped to active on plan %s/%s "
        "(seats=%d)",
        org_id, plan_code, billing_cycle, seats,
    )

    # Step 20 — welcome / upgrade email. `plan_changed` is the same
    # template for "trial → first paid plan" and "paid → different
    # paid plan"; both surfaces are best served by the same congratu-
    # latory copy plus a deep link into Billing settings. The
    # `payment_succeeded` email fires separately when Stripe's
    # `invoice.paid` lands, so the customer gets exactly two messages
    # for one upgrade (welcome + receipt).
    plan = plans.get(plan_code)
    await send_billing_email(
        org_id=org_id,
        template_key="plan_changed",
        context={
            "plan_name": plan.name if plan is not None else plan_code.title(),
        },
    )
