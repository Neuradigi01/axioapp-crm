"""Subscription service — read + write helpers.

Read paths (Step 1 / 7):
  - `get_active_subscription` — single-row lookup by org.
  - `compose_current_subscription_response` — composed read for the
    billing page.

Write paths:
  - Step 6: `create_trial_subscription` (signup hook, lives in
    `signup_hook.py`).
  - Step 8: `change_plan` (this file). Handles the four outcomes —
    `no_change`, `needs_payment`, `scheduled`, plus 4xx for the
    rule-violation cases (seats below in-use, target=trial, …).
  - Step 9: `change_seats` — slimmer variant; not implemented yet.
  - Step 10: `cancel_subscription` — not implemented yet.

Reads are scoped by the active org via the `TenantScoped` ORM mixin
(see `shared/orm.py`) and Postgres RLS — the service does NOT add an
explicit `org_id = ?` predicate because the loader already does it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.subscriptions import plans
from src.app.core.subscriptions.models import (
    ACTIVE_STATUSES,
    Subscription,
    SubscriptionInvoice,
)
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
from src.app.core.users import data_access


# Cycle lengths used when projecting `first_renewal_at` in the preview.
# Kept here (rather than importing `tasks._CYCLE_LENGTHS`) so the
# service has no dependency on the Celery layer.
_CYCLE_DAYS: dict[str, int] = {"monthly": 30, "annual": 365}


# Marker constant: returned in `ScheduledPreview.remaining_period_credit`.
# Documented as a constant rather than inline so the marketing copy
# stays consistent across responses.
_REMAINING_CREDIT_NOTE = "kept until renewal"


async def get_active_subscription(
    session: AsyncSession, org_id: uuid.UUID
) -> Subscription | None:
    """Return the org's currently-active subscription, or None.

    "Active" here means `status` is one of `(trialing, active, past_due,
    read_only)` — the same set the partial unique index enforces. Rows
    in `archived` or `cancelled` are history and ignored.

    The `org_id` argument is required even though `TenantScoped` would
    auto-filter on a context-bound session: callers in background tasks
    (Step 6 lifecycle, Step 13 webhooks) may have no request context.
    Passing the id explicitly makes both call shapes work.
    """
    stmt = (
        select(Subscription)
        .where(
            Subscription.org_id == org_id,
            Subscription.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def compose_current_subscription_response(
    session: AsyncSession, org_id: uuid.UUID
) -> SubscriptionCurrentResponse:
    """Compose the read response for `GET /api/v1/subscriptions/current`.

    Folds together the four facets the billing page needs:
      1. the active subscription row,
      2. its plan from the registry,
      3. the count of active org members (= `seats.in_use`),
      4. the metered-resource usage snapshot.

    Raises 404 when no active subscription exists — the frontend treats
    that as "needs to pick a plan." Post the Step 2 backfill this should
    not happen for a real org, but the endpoint is defensive.

    A subscription pointing at a plan code the YAML registry no longer
    carries is a hard data error and raises ``RuntimeError`` — mirrors
    the entitlement service's behaviour on the same condition so the
    surfaces are consistent.
    """
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
        raise RuntimeError(
            f"subscription {sub.id} references unknown plan {sub.plan_code!r}"
        )
    seats_in_use = await data_access.count_active_members(session, org_id)
    usage_snap = await usage_service.snapshot(
        session, org_id, list(RESOURCE_PERIOD_KIND.keys())
    )
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
    """Apply or schedule a plan / cycle / seat change.

    Four outcomes:
      - `no_change` — request already matches the live row.
      - `needs_payment` — target costs more per period (upgrade, paid
        cycle-up, or seat addition); the actual Stripe checkout is
        wired in Step 12, so `checkout_url`/`checkout_session_id` stay
        null here.
      - `scheduled` — target costs the same or less per period
        (downgrade, paid cycle-down, or seat reduction); the change
        is parked on `next_*` columns and applied at the next period
        boundary by the lifecycle task.

    Raises 400 for business-rule violations (trial-target, cancelled
    sub, seats below in-use, seats below bundle minimum) and 404 for
    an unknown `to_plan`.
    """
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        # Cancelled / no-sub orgs surface as 400 per the spec — the
        # frontend handles "you need a new sub" as a separate flow.
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
        # Same defensive check as `compose_current_subscription_response`.
        raise RuntimeError(
            f"subscription {sub.id} references unknown plan {sub.plan_code!r}"
        )

    effective_seats = seats if seats is not None else sub.seats_purchased
    seats_in_use = await data_access.count_active_members(session, org_id)
    _validate_change(target_plan, effective_seats, seats_in_use)

    # No-change short-circuit — also catches a duplicate request that
    # already matches the prior scheduled change (idempotent).
    if (
        to_plan == sub.plan_code
        and billing_cycle == sub.billing_cycle
        and effective_seats == sub.seats_purchased
    ):
        return NoChangeResponse(outcome="no_change")

    if _is_upgrade(
        current_plan, target_plan,
        target_cycle=billing_cycle, current_cycle=sub.billing_cycle,
        target_seats=effective_seats, current_seats=sub.seats_purchased,
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
            # Step 12 wires a real `PaymentProvider` here; until then
            # the frontend renders the preview and hides the
            # "Continue to Stripe" button.
            checkout_url=None,
            checkout_session_id=None,
            preview=_preview_needs_payment(
                target_plan, billing_cycle, effective_seats,
            ),
        )

    # Downgrade / cycle-down / seat reduction → schedule on the row.
    was_rescheduled = sub.next_plan_code is not None
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(
            next_plan_code=to_plan,
            next_billing_cycle=billing_cycle,
            next_seats=effective_seats,
        )
    )
    await session.commit()
    await audit.log(
        "subscription.change_rescheduled"
        if was_rescheduled
        else "subscription.change_scheduled",
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
    target_plan: Plan, effective_seats: int, seats_in_use: int,
) -> None:
    """Enforce the four business rules before deciding outcome.

    Order is significant: the trial-target check fires first because
    a request targeting trial is always wrong regardless of seats.
    Seat checks emit `min_allowed` so the UI can pre-fill the next
    valid value without round-tripping.
    """
    if target_plan.code == "trial":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "cannot_change_to_trial"},
        )

    # Manager spec 2026-06-11: minimum is 1 seat for any plan, with no
    # active-member floor. `included_seats` still drives bundle pricing
    # — buy below the bundle and you pay the bundle price for fewer
    # included seats — but the customer is allowed to do it. Orgs may
    # legitimately run "over-subscribed" (more active members than paid
    # seats) and the manager owns that trade-off. `seats_in_use` stays
    # on the signature so the read response can still surface it, but
    # this validator no longer consults it.
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
    """Classify the requested transition as "needs payment now" or not.

    Comparison order:
      1. Tier — when codes differ, the higher monthly bundle wins.
      2. Cycle — same tier, monthly → annual is an upgrade (pre-pays a
         year). Annual → monthly is treated as a downgrade.
      3. Seats — same tier + same cycle, adding seats is an upgrade,
         removing seats is a scheduled downgrade.
    """
    if target_plan.code != current_plan.code:
        return (
            target_plan.pricing.monthly_bundle_usd
            > current_plan.pricing.monthly_bundle_usd
        )
    if target_cycle != current_cycle:
        return target_cycle == "annual"
    return target_seats > current_seats


def _preview_needs_payment(
    target_plan: Plan, billing_cycle: str, seats: int,
) -> NeedsPaymentPreview:
    """Build the preview payload for an upgrade.

    Best-effort: this is the cost of one fresh period on the target
    plan at the requested seat count. The exact prorated number from
    Stripe (factoring in unused days of the current cycle) is
    surfaced by Step 12's checkout response.
    """
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
        first_renewal_at=datetime.now(tz=timezone.utc)
        + timedelta(days=cycle_days),
    )


# ---------------------------------------------------------------------------
# Seat management — Step 9
# ---------------------------------------------------------------------------


async def preview_seat_change(
    session: AsyncSession, org_id: uuid.UUID, total_seats: int,
) -> SeatPreview:
    """Pure read — show the cost impact of moving to `total_seats`
    without committing anything.

    Raises 400 only when the org has no active subscription. The
    rule violations (below in-use / bundle min, trial-add) are NOT
    raised here — preview is informational and the UI surfaces them
    via `outcome_if_committed`. The actual commit endpoint is the
    enforcement boundary.
    """
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_active_subscription"},
        )
    plan = plans.get(sub.plan_code)
    if plan is None:
        raise RuntimeError(
            f"subscription {sub.id} references unknown plan {sub.plan_code!r}"
        )
    return _compute_seat_preview(sub, plan, total_seats)


async def change_seats(
    session: AsyncSession, org_id: uuid.UUID, *, total_seats: int,
) -> (
    SeatChangeNeedsPaymentResponse
    | SeatChangeScheduledResponse
    | NoChangeResponse
):
    """Apply or schedule a seat change for the caller's org.

    Three outcomes:
      - `no_change` — request matches `seats_purchased`.
      - `needs_payment` — adding seats (paid plan only); the actual
        Stripe checkout lands in Step 12, so `checkout_url` stays null.
      - `scheduled` — reducing seats; parked on `next_seats` and
        applied at the next period boundary by the lifecycle task.
    """
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
        raise RuntimeError(
            f"subscription {sub.id} references unknown plan {sub.plan_code!r}"
        )

    # No-change short-circuit fires before any validation — a request
    # for the current count is always a no-op, even if the org is over
    # its seat cap (overage reconciliation is a separate flow).
    if total_seats == sub.seats_purchased:
        return NoChangeResponse(outcome="no_change")

    seats_in_use = await data_access.count_active_members(session, org_id)

    if total_seats < sub.seats_purchased:
        # Reducing — only the bundle floor (1) applies. Per manager spec
        # 2026-06-11 the active-member floor was dropped; orgs may run
        # over-subscribed and the manager owns that trade-off.
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
        await session.execute(
            update(Subscription)
            .where(Subscription.id == sub.id)
            .values(next_seats=total_seats)
        )
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
    sub: Subscription, plan: Plan, total_seats: int,
) -> SeatPreview:
    """Math for both the read-only preview endpoint and the commit
    response.

    `amount_due_usd` is a best-effort proration estimate matching the
    formula in the spec — Stripe's own per-day proration in Step 12
    may differ by a few cents, which the UI discloses.
    """
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

        now = datetime.now(tz=timezone.utc)
        period_total = (
            sub.current_period_end - sub.current_period_start
        ).total_seconds()
        period_remaining = (sub.current_period_end - now).total_seconds()
        if period_total <= 0:
            fraction = 0.0
        else:
            fraction = max(0.0, min(1.0, period_remaining / period_total))
        amount_due = round(delta * extra_seat_period_cost * fraction)
    else:
        outcome = "scheduled"
        amount_due = 0

    # Project the per-cycle running cost at the new seat count. Only
    # the side matching the current cycle is filled; the other stays
    # null so the UI doesn't show a confusing "you'll also pay $X
    # annually" line when the user is on monthly billing.
    extras_after = max(0, total_seats - plan.pricing.included_seats)
    if sub.billing_cycle == "monthly":
        monthly_cost: int | None = (
            plan.pricing.monthly_bundle_usd
            + extras_after * plan.pricing.extra_seat_monthly_usd
        )
        annual_cost: int | None = None
    else:
        monthly_cost = None
        annual_cost = (
            plan.pricing.annual_bundle_usd
            + extras_after * plan.pricing.extra_seat_annual_usd
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
    session: AsyncSession, org_id: uuid.UUID,
) -> CancelSubscriptionResponse:
    """Mark the org's subscription cancelled. Idempotent.

    Looks up the most-recent subscription row regardless of status —
    `get_active_subscription` filters out `cancelled`, but the
    idempotent path needs to see a cancelled row to short-circuit.

    The Stripe-side cancellation lands in Step 13's webhook (the local
    status flip here is enough to invalidate write access via Step 10's
    middleware — Stripe will follow when the webhook fires from the
    operator-side cancel).

    Raises 404 only if the org has *no* subscription rows at all — a
    pathological state that shouldn't happen post Step 2's backfill.
    """
    latest = (
        await session.execute(
            select(Subscription)
            .where(Subscription.org_id == org_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_subscription"},
        )

    if latest.status == "cancelled":
        # Idempotent path. `cancelled_at` is guaranteed non-null
        # whenever `status == 'cancelled'` because the only writer
        # (this function) sets them together.
        return CancelSubscriptionResponse(
            status="cancelled",
            cancelled_at=latest.cancelled_at,  # type: ignore[arg-type]
            already_cancelled=True,
        )

    now = datetime.now(tz=timezone.utc)
    # Conditional UPDATE on status so a concurrent webhook flip to
    # `cancelled` (Step 13) cannot produce a double `cancelled_at`.
    result = await session.execute(
        update(Subscription)
        .where(
            Subscription.id == latest.id,
            Subscription.status != "cancelled",
        )
        .values(status="cancelled", cancelled_at=now)
    )
    await session.commit()

    if (result.rowcount or 0) == 0:
        # Lost the race — re-read for the canonical `cancelled_at`.
        refreshed = (
            await session.execute(
                select(Subscription).where(Subscription.id == latest.id)
            )
        ).scalar_one()
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
    """Return the org's Stripe customer ID, creating one if absent.

    Idempotent — once `stripe_customer_id` is populated on the
    subscription row, subsequent calls short-circuit without touching
    Stripe. The row is updated via a conditional UPDATE that only
    fires when the column is still NULL, so a concurrent webhook flip
    (Step 13) cannot collide with this write.
    """
    if sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer_id = await payment_provider.create_customer(
        org_id=sub.org_id, email=email, name=name,
    )
    result = await session.execute(
        update(Subscription)
        .where(
            Subscription.id == sub.id,
            Subscription.stripe_customer_id.is_(None),
        )
        .values(stripe_customer_id=customer_id)
    )
    await session.commit()
    if (result.rowcount or 0) == 0:
        # A concurrent flow filled the column in. Re-read so we return
        # the canonical value rather than the one we just minted.
        refreshed = (
            await session.execute(
                select(Subscription).where(Subscription.id == sub.id)
            )
        ).scalar_one()
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
    """Validate the requested upgrade and open a Stripe Checkout session.

    Shares the plan-change rule set (`_validate_change`) so the
    trial-banner upgrade flow refuses the same edge cases as
    `change_plan`. Persists the resulting Checkout Session ID on the
    subscription row for Step 13's webhook to correlate.

    Raises 400 for rule violations, 404 for unknown plan codes, and
    `RuntimeError` for a stale `plan_code` on the subscription row
    (mirrors `compose_current_subscription_response`).
    """
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

    seats_in_use = await data_access.count_active_members(session, org_id)
    _validate_change(target_plan, seats, seats_in_use)

    customer_id = await ensure_stripe_customer(
        session, sub,
        email=user_email, name=user_full_name,
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

    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(pending_checkout_session_id=checkout.session_id)
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
    """Augment a `NeedsPaymentResponse` with a real Stripe checkout URL.

    Returns a new response object with `checkout_url` and
    `checkout_session_id` filled. Used by the plan-change and
    seat-change routes when the provider is configured.

    The preview block from the original response is preserved
    verbatim — it's already correct and the Stripe URL is purely
    additive.
    """
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        # Cannot happen post the inner change_plan call that produced
        # the needs_payment response — defensive.
        return response

    customer_id = await ensure_stripe_customer(
        session, sub,
        email=user_email, name=user_full_name,
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
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(pending_checkout_session_id=checkout.session_id)
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
    """Augment a seat-change needs_payment response with a checkout URL.

    Mirrors `attach_checkout_to_needs_payment` for the seat-change
    response shape — the two share the underlying flow but carry
    different preview models so the augment functions stay separate.
    """
    sub = await get_active_subscription(session, org_id)
    if sub is None:
        return response

    customer_id = await ensure_stripe_customer(
        session, sub,
        email=user_email, name=user_full_name,
        payment_provider=payment_provider,
    )
    # For a seat-only change the plan stays the same; only quantity
    # moves. Stripe still expects a Price ID so we pass the live plan.
    checkout = await payment_provider.create_checkout_session(
        org_id=org_id,
        customer_id=customer_id,
        plan_code=sub.plan_code,
        billing_cycle=sub.billing_cycle,
        seats=response.preview.to_seats,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    await session.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(pending_checkout_session_id=checkout.session_id)
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
    session: AsyncSession, org_id: uuid.UUID,
) -> list[InvoiceRead]:
    """Return every Stripe invoice mirrored for the org, newest first.

    The list is materialised end-to-end (no pagination) because v1
    orgs collect ≤ 24 invoices per year; the billing-settings page
    renders them inline and a paged list would add UX cost for no
    real benefit at this scale. Step 19's audit-log view is the
    pattern to follow if pagination becomes warranted later.

    `org_id` is passed explicitly so the query is self-scoping; the
    `TenantScoped` ORM listener also auto-injects the predicate when
    the request context is set, so this is belt-and-suspenders.
    """
    rows = (
        await session.execute(
            select(SubscriptionInvoice)
            .where(SubscriptionInvoice.org_id == org_id)
            .order_by(SubscriptionInvoice.created_at.desc())
        )
    ).scalars().all()
    return [InvoiceRead.model_validate(row) for row in rows]
