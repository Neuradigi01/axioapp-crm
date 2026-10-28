"""Subscription service — read + write helpers.

Read paths (Step 1 / 7):
  - `get_active_subscription` — single-row lookup by org.
  - `compose_current_subscription_response` — composed read for the
    billing page.

Write paths:
  - Step 6: `create_trial_subscription` (signup hook, lives in
    `signup_hook.py`).
  - Step 8: `change_plan` — outcomes: `no_change`, `needs_payment`,
    `scheduled`, plus 4xx for the rule-violation cases.
  - Step 9: `change_seats` — slimmer variant.
  - Step 10: `cancel_subscription`.

Reads are scoped by the active org via the `TenantScoped` ORM mixin
(see `shared/orm.py`) and Postgres RLS — the service does NOT add an
explicit `org_id = ?` predicate because the loader already does it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions import data_access as _da
from src.app.core.subscriptions import plans
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.plans import Plan
from src.app.core.subscriptions.schemas import (
    BillingCycle,
    CancelSubscriptionResponse,
    CheckoutResponse,
    InvoiceRead,
    NeedsPaymentPreview,
    NeedsPaymentResponse,
    NoChangeResponse,
    ScheduledPreview,
    ScheduledResponse,
    SeatChangeNeedsPaymentResponse,
    SeatChangeScheduledResponse,
    SeatPreview,
    SubscriptionCurrentResponse,
)
from src.app.core.users import service as users_service

# Cycle lengths used when projecting `first_renewal_at` in the preview.
_CYCLE_DAYS: dict[str, int] = {"monthly": 30, "annual": 365}


# Marker constant: returned in `ScheduledPreview.remaining_period_credit`.
_REMAINING_CREDIT_NOTE = "kept until renewal"


async def get_active_subscription(session: AsyncSession, org_id: uuid.UUID) -> Subscription | None:
    """Return the org's currently-active subscription, or None."""
    return await _da.get_active_subscription_for_org(session, org_id)


async def compose_current_subscription_response(
    session: AsyncSession, org_id: uuid.UUID
) -> SubscriptionCurrentResponse:
    """Compose the read response for `GET /api/v1/subscriptions/current`."""
    # Local import: `usage_service` imports `get_active_subscription`
    # from this module, so a top-level import would deadlock the loader.
    from src.app.core.subscriptions import usage_service
    from src.app.core.subscriptions.usage_service import RESOURCE_PERIOD_KIND

    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription",
        )
    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(f"subscription {sub.id} references unknown plan {sub.plan_code!r}")
    seats_in_use = await users_service.count_active_members(session, org_id)
    usage_snap = await usage_service.snapshot(session, org_id, list(RESOURCE_PERIOD_KIND.keys()))
    return SubscriptionCurrentResponse.from_components(
        sub=sub,
        plan=plan,
        seats_in_use=seats_in_use,
        usage_snapshot=usage_snap,
    )


# ---------------------------------------------------------------------------
# Plan change — Step 8
# ---------------------------------------------------------------------------


async def change_plan(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    to_plan: str,
    billing_cycle: BillingCycle,
    seats: int | None,
) -> NeedsPaymentResponse | ScheduledResponse | NoChangeResponse:
    """Apply or schedule a plan / cycle / seat change."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_subscription"},
        )
    if sub.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "cannot_change_cancelled"},
        )

    target_plan = plans.get(to_plan)
    if target_plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_plan", "to_plan": to_plan},
        )
    current_plan = plans.get(sub.plan_code)
    if current_plan is None:
        raise RuntimeError(f"subscription {sub.id} references unknown plan {sub.plan_code!r}")

    effective_seats = seats if seats is not None else sub.seats_purchased
    seats_in_use = await users_service.count_active_members(session, org_id)
    _validate_change(target_plan, effective_seats, seats_in_use)

    if (
        to_plan == sub.plan_code
        and billing_cycle == sub.billing_cycle
        and effective_seats == sub.seats_purchased
    ):
        return NoChangeResponse(outcome="no_change")

    if _is_upgrade(
        current_plan,
        target_plan,
        target_cycle=billing_cycle,
        current_cycle=sub.billing_cycle,
        target_seats=effective_seats,
        current_seats=sub.seats_purchased,
    ):
        await audit.log(
            "subscription.change_initiated",
            entity_type="subscription",
            entity_id=sub.id,
            before={
                "plan_code": sub.plan_code,
                "billing_cycle": sub.billing_cycle,
                "seats_purchased": sub.seats_purchased,
            },
            after={
                "to_plan": to_plan,
                "billing_cycle": billing_cycle,
                "seats": effective_seats,
            },
        )
        return NeedsPaymentResponse(
            outcome="needs_payment",
            checkout_url=None,
            checkout_session_id=None,
            preview=_preview_needs_payment(
                target_plan,
                billing_cycle,
                effective_seats,
            ),
        )

    # Downgrade / cycle-down / seat reduction → schedule on the row.
    was_rescheduled = sub.next_plan_code is not None
    await _da.update_subscription_next_plan_fields(
        session,
        sub_id=sub.id,
        next_plan_code=to_plan,
        next_billing_cycle=billing_cycle,
        next_seats=effective_seats,
    )
    await session.commit()
    await audit.log(
        "subscription.change_rescheduled" if was_rescheduled else "subscription.change_scheduled",
        entity_type="subscription",
        entity_id=sub.id,
        before={
            "plan_code": sub.plan_code,
            "billing_cycle": sub.billing_cycle,
            "seats_purchased": sub.seats_purchased,
        },
        after={
            "to_plan": to_plan,
            "billing_cycle": billing_cycle,
            "seats": effective_seats,
            "effective_at": sub.current_period_end.isoformat(),
        },
    )
    return ScheduledResponse(
        outcome="scheduled",
        effective_at=sub.current_period_end,
        from_plan=sub.plan_code,
        to_plan=to_plan,
        preview=ScheduledPreview(
            amount_due_usd=0,
            remaining_period_credit=_REMAINING_CREDIT_NOTE,
        ),
    )


def _validate_change(
    target_plan: Plan,
    effective_seats: int,
    seats_in_use: int,
) -> None:
    """Enforce the four business rules before deciding outcome."""
    if target_plan.code == "trial":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "cannot_change_to_trial"},
        )

    # Manager spec 2026-06-11: minimum is 1 seat for any plan.
    bundle_min = 1
    if effective_seats < bundle_min:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "seats_below_minimum",
                "min_allowed": bundle_min,
            },
        )


def _is_upgrade(
    current_plan: Plan,
    target_plan: Plan,
    *,
    target_cycle: str,
    current_cycle: str,
    target_seats: int,
    current_seats: int,
) -> bool:
    """Classify the requested transition as "needs payment now" or not."""
    if target_plan.code != current_plan.code:
        return target_plan.pricing.monthly_bundle_usd > current_plan.pricing.monthly_bundle_usd
    if target_cycle != current_cycle:
        return target_cycle == "annual"
    return target_seats > current_seats


def _preview_needs_payment(
    target_plan: Plan,
    billing_cycle: str,
    seats: int,
) -> NeedsPaymentPreview:
    """Build the preview payload for an upgrade."""
    if billing_cycle == "annual":
        bundle = target_plan.pricing.annual_bundle_usd
        extra_seat_cost = target_plan.pricing.extra_seat_annual_usd
    else:
        bundle = target_plan.pricing.monthly_bundle_usd
        extra_seat_cost = target_plan.pricing.extra_seat_monthly_usd

    extras = max(0, seats - target_plan.pricing.included_seats)
    amount_due = bundle + extras * extra_seat_cost
    cycle_days = _CYCLE_DAYS[billing_cycle]

    return NeedsPaymentPreview(
        to_plan=target_plan.code,
        billing_cycle=billing_cycle,  # type: ignore[arg-type]
        seats=seats,
        amount_due_usd=amount_due,
        first_renewal_at=datetime.now(tz=UTC) + timedelta(days=cycle_days),
    )


# ---------------------------------------------------------------------------
# Seat management — Step 9
# ---------------------------------------------------------------------------


async def preview_seat_change(
    session: AsyncSession,
    org_id: uuid.UUID,
    total_seats: int,
) -> SeatPreview:
    """Pure read — show the cost impact of moving to `total_seats`."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_subscription"},
        )
    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(f"subscription {sub.id} references unknown plan {sub.plan_code!r}")
    return _compute_seat_preview(sub, plan, total_seats)


async def change_seats(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    total_seats: int,
) -> SeatChangeNeedsPaymentResponse | SeatChangeScheduledResponse | NoChangeResponse:
    """Apply or schedule a seat change for the caller's org."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_subscription"},
        )
    if sub.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "cannot_change_cancelled"},
        )

    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(f"subscription {sub.id} references unknown plan {sub.plan_code!r}")

    if total_seats == sub.seats_purchased:
        return NoChangeResponse(outcome="no_change")

    if total_seats < sub.seats_purchased:
        bundle_min = 1
        if total_seats < bundle_min:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "seats_below_minimum",
                    "min_allowed": bundle_min,
                },
            )

        was_rescheduled = sub.next_seats is not None
        await _da.update_subscription_next_seats(session, sub_id=sub.id, next_seats=total_seats)
        await session.commit()
        await audit.log(
            "subscription.seats_change_rescheduled"
            if was_rescheduled
            else "subscription.seats_change_scheduled",
            entity_type="subscription",
            entity_id=sub.id,
            before={"seats_purchased": sub.seats_purchased},
            after={
                "to_seats": total_seats,
                "effective_at": sub.current_period_end.isoformat(),
            },
        )
        return SeatChangeScheduledResponse(
            outcome="scheduled",
            effective_at=sub.current_period_end,
            from_seats=sub.seats_purchased,
            to_seats=total_seats,
            refund_due_usd=0,
        )

    # Adding seats path.
    if sub.plan_code == "trial":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "trial_cannot_add_seats"},
        )

    await audit.log(
        "subscription.seats_change_initiated",
        entity_type="subscription",
        entity_id=sub.id,
        before={"seats_purchased": sub.seats_purchased},
        after={"to_seats": total_seats},
    )
    preview = _compute_seat_preview(sub, plan, total_seats)
    return SeatChangeNeedsPaymentResponse(
        outcome="needs_payment",
        checkout_url=None,
        checkout_session_id=None,
        preview=preview,
    )


def _compute_seat_preview(
    sub: Subscription,
    plan: Plan,
    total_seats: int,
) -> SeatPreview:
    """Math for both the read-only preview endpoint and the commit response."""
    delta = total_seats - sub.seats_purchased

    if delta == 0:
        outcome: str = "no_change"
        amount_due = 0
    elif delta > 0:
        outcome = "needs_payment"
        if sub.billing_cycle == "annual":
            extra_seat_period_cost = plan.pricing.extra_seat_annual_usd
        else:
            extra_seat_period_cost = plan.pricing.extra_seat_monthly_usd

        now = datetime.now(tz=UTC)
        period_total = (sub.current_period_end - sub.current_period_start).total_seconds()
        period_remaining = (sub.current_period_end - now).total_seconds()
        if period_total <= 0:
            fraction = 0.0
        else:
            fraction = max(0.0, min(1.0, period_remaining / period_total))
        amount_due = round(delta * extra_seat_period_cost * fraction)
    else:
        outcome = "scheduled"
        amount_due = 0

    extras_after = max(0, total_seats - plan.pricing.included_seats)
    if sub.billing_cycle == "monthly":
        monthly_cost: int | None = (
            plan.pricing.monthly_bundle_usd + extras_after * plan.pricing.extra_seat_monthly_usd
        )
        annual_cost: int | None = None
    else:
        monthly_cost = None
        annual_cost = (
            plan.pricing.annual_bundle_usd + extras_after * plan.pricing.extra_seat_annual_usd
        )

    return SeatPreview(
        from_seats=sub.seats_purchased,
        to_seats=total_seats,
        delta=delta,
        outcome_if_committed=outcome,  # type: ignore[arg-type]
        amount_due_usd=amount_due,
        next_renewal_at=sub.current_period_end,
        monthly_cost_after_change_usd=monthly_cost,
        annual_cost_after_change_usd=annual_cost,
    )


# ---------------------------------------------------------------------------
# Cancellation — Step 10
# ---------------------------------------------------------------------------


async def cancel_subscription(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> CancelSubscriptionResponse:
    """Mark the org's subscription cancelled. Idempotent."""
    latest = await _da.get_latest_subscription_for_org(session, org_id)
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_subscription"},
        )

    if latest.status == "cancelled":
        return CancelSubscriptionResponse(
            status="cancelled",
            cancelled_at=latest.cancelled_at,  # type: ignore[arg-type]
            already_cancelled=True,
        )

    now = datetime.now(tz=UTC)
    rowcount = await _da.update_subscription_cancelled_conditional(
        session, sub_id=latest.id, when=now
    )
    await session.commit()

    if rowcount == 0:
        # Lost the race — re-read for the canonical `cancelled_at`.
        refreshed = await _da.get_subscription_by_id(session, latest.id)
        assert refreshed is not None
        return CancelSubscriptionResponse(
            status="cancelled",
            cancelled_at=refreshed.cancelled_at,  # type: ignore[arg-type]
            already_cancelled=True,
        )

    await audit.log(
        "subscription.cancelled",
        entity_type="subscription",
        entity_id=latest.id,
        before={"status": latest.status},
        after={"status": "cancelled", "cancelled_at": now.isoformat()},
    )
    return CancelSubscriptionResponse(
        status="cancelled",
        cancelled_at=now,
        already_cancelled=False,
    )


# ---------------------------------------------------------------------------
# Checkout integration — Step 12
# ---------------------------------------------------------------------------


async def ensure_stripe_customer(
    session: AsyncSession,
    sub: Subscription,
    *,
    email: str,
    name: str,
    payment_provider,
) -> str:
    """Return the org's Stripe customer ID, creating one if absent."""
    if sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer_id = await payment_provider.create_customer(
        org_id=sub.org_id,
        email=email,
        name=name,
    )
    rowcount = await _da.update_subscription_stripe_customer_conditional(
        session, sub_id=sub.id, customer_id=customer_id
    )
    await session.commit()
    if rowcount == 0:
        # A concurrent flow filled the column in. Re-read so we return
        # the canonical value rather than the one we just minted.
        refreshed = await _da.get_subscription_by_id(session, sub.id)
        assert refreshed is not None
        return refreshed.stripe_customer_id or customer_id
    return customer_id


async def create_direct_checkout(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    to_plan: str,
    billing_cycle: BillingCycle,
    seats: int,
    success_url: str,
    cancel_url: str,
    user_email: str,
    user_full_name: str,
    payment_provider,
) -> CheckoutResponse:
    """Validate the requested upgrade and open a Stripe Checkout session."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_subscription"},
        )
    if sub.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "cannot_change_cancelled"},
        )

    target_plan = plans.get(to_plan)
    if target_plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_plan", "to_plan": to_plan},
        )

    seats_in_use = await users_service.count_active_members(session, org_id)
    _validate_change(target_plan, seats, seats_in_use)

    customer_id = await ensure_stripe_customer(
        session,
        sub,
        email=user_email,
        name=user_full_name,
        payment_provider=payment_provider,
    )

    checkout = await payment_provider.create_checkout_session(
        org_id=org_id,
        customer_id=customer_id,
        plan_code=to_plan,
        billing_cycle=billing_cycle,
        seats=seats,
        success_url=success_url,
        cancel_url=cancel_url,
    )

    await _da.update_subscription_pending_checkout(
        session, sub_id=sub.id, session_id=checkout.session_id
    )
    await session.commit()
    await audit.log(
        "subscription.checkout_started",
        entity_type="subscription",
        entity_id=sub.id,
        after={
            "to_plan": to_plan,
            "billing_cycle": billing_cycle,
            "seats": seats,
            "checkout_session_id": checkout.session_id,
        },
    )

    return CheckoutResponse(
        checkout_url=checkout.url,
        session_id=checkout.session_id,
    )


async def attach_checkout_to_needs_payment(
    session: AsyncSession,
    org_id: uuid.UUID,
    response: NeedsPaymentResponse,
    *,
    success_url: str,
    cancel_url: str,
    user_email: str,
    user_full_name: str,
    payment_provider,
) -> NeedsPaymentResponse:
    """Augment a `NeedsPaymentResponse` with a real Stripe checkout URL."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        return response

    customer_id = await ensure_stripe_customer(
        session,
        sub,
        email=user_email,
        name=user_full_name,
        payment_provider=payment_provider,
    )
    checkout = await payment_provider.create_checkout_session(
        org_id=org_id,
        customer_id=customer_id,
        plan_code=response.preview.to_plan,
        billing_cycle=response.preview.billing_cycle,
        seats=response.preview.seats,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    await _da.update_subscription_pending_checkout(
        session, sub_id=sub.id, session_id=checkout.session_id
    )
    await session.commit()

    return NeedsPaymentResponse(
        outcome="needs_payment",
        checkout_url=checkout.url,
        checkout_session_id=checkout.session_id,
        preview=response.preview,
    )


async def attach_checkout_to_seats_needs_payment(
    session: AsyncSession,
    org_id: uuid.UUID,
    response: SeatChangeNeedsPaymentResponse,
    *,
    success_url: str,
    cancel_url: str,
    user_email: str,
    user_full_name: str,
    payment_provider,
) -> SeatChangeNeedsPaymentResponse:
    """Augment a seat-change needs_payment response with a checkout URL."""
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        return response

    customer_id = await ensure_stripe_customer(
        session,
        sub,
        email=user_email,
        name=user_full_name,
        payment_provider=payment_provider,
    )
    checkout = await payment_provider.create_checkout_session(
        org_id=org_id,
        customer_id=customer_id,
        plan_code=sub.plan_code,
        billing_cycle=sub.billing_cycle,
        seats=response.preview.to_seats,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    await _da.update_subscription_pending_checkout(
        session, sub_id=sub.id, session_id=checkout.session_id
    )
    await session.commit()

    return SeatChangeNeedsPaymentResponse(
        outcome="needs_payment",
        checkout_url=checkout.url,
        checkout_session_id=checkout.session_id,
        preview=response.preview,
    )


# ---------------------------------------------------------------------------
# Invoice list — Step 13.c
# ---------------------------------------------------------------------------


async def list_invoices(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> list[InvoiceRead]:
    """Return every Stripe invoice mirrored for the org, newest first."""
    rows = await _da.list_invoices_for_org(session, org_id)
    return [InvoiceRead.model_validate(row) for row in rows]
