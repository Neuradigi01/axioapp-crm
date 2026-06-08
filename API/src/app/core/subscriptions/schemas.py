"""Pydantic schemas for the subscription model.

Two shapes live here:

  - ``SubscriptionRead`` — the raw row, used by internal write paths
    in Steps 8-10 (plan change, seat change, cancellation).
  - ``SubscriptionCurrentResponse`` — the composed read shape returned
    by ``GET /api/v1/subscriptions/current`` (Step 7). Folds the plan
    metadata, active seat count, and usage snapshot into one payload so
    the in-app billing page (Step 16) and trial banner (Step 15) load
    in a single round-trip.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.plans import Plan


SubscriptionStatus = Literal[
    "trialing",
    "active",
    "past_due",
    "read_only",
    "archived",
    "cancelled",
]

BillingCycle = Literal["monthly", "annual"]


class SubscriptionRead(BaseModel):
    """Full read shape of a `subscriptions` row.

    Composed responses (the in-app billing page, the trial banner) build
    on top of this in Step 7 by overlaying plan metadata and usage.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    plan_code: str
    status: SubscriptionStatus
    billing_cycle: BillingCycle
    seats_purchased: int

    trial_started_at: datetime | None
    trial_ends_at: datetime | None
    current_period_start: datetime
    current_period_end: datetime
    read_only_at: datetime | None
    archived_at: datetime | None
    cancelled_at: datetime | None

    stripe_customer_id: str | None
    stripe_subscription_id: str | None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Composed read response — `GET /api/v1/subscriptions/current`
# ---------------------------------------------------------------------------


class PlanShort(BaseModel):
    """Plan fields the billing page renders. Caps and feature flags live
    on the registry — clients that need them fetch `/api/v1/plans`."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    monthly_bundle_usd: int
    annual_bundle_usd: int
    extra_seat_monthly_usd: int
    extra_seat_annual_usd: int
    included_seats: int


class TrialInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    ends_at: datetime
    days_remaining: int


class PeriodInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    renews_at: datetime


class SeatsInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included: int
    purchased: int
    in_use: int
    extra_seat_cost_per_period_usd: int


class UsageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    current: int
    cap: int
    is_unlimited: bool


class SubscriptionCurrentResponse(BaseModel):
    """Composed payload for the in-app billing page.

    Built via ``from_components`` to keep the composition logic alongside
    the schema definition — the route handler does no derivation, just
    delegates to the service which delegates here.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    plan: PlanShort
    status: SubscriptionStatus
    billing_cycle: BillingCycle
    trial: TrialInfo | None
    period: PeriodInfo
    seats: SeatsInfo
    usage: list[UsageRow]
    read_only: bool
    archived: bool
    cancelled: bool
    stripe_customer_id: str | None
    stripe_subscription_id: str | None

    @classmethod
    def from_components(
        cls,
        *,
        sub: Subscription,
        plan: Plan,
        seats_in_use: int,
        usage_snapshot: dict[str, int],
        now: datetime | None = None,
    ) -> "SubscriptionCurrentResponse":
        """Compose the response from its four inputs.

        ``now`` is injectable so tests can pin time; production passes
        ``None`` and the method reads ``datetime.now(tz=UTC)``.

        The composition rules:
          - ``trial`` is ``None`` unless both ``trial_started_at`` and
            ``trial_ends_at`` are set on the subscription row.
          - ``trial.days_remaining`` is ceil((ends_at - now) / 1 day),
            floored at 0 — a trial that ended in the past must not
            surface as negative.
          - ``seats.extra_seat_cost_per_period_usd`` flips with the
            billing cycle so the UI can render the correct per-cycle
            number without re-reading the plan.
          - ``usage[]`` carries one row per key in ``usage_snapshot``;
            the cap is pulled from the plan's caps. ``is_unlimited`` is
            ``True`` exactly when the cap is the ``-1`` sentinel.
          - ``read_only`` / ``archived`` / ``cancelled`` are the three
            terminal-ish status flags reified as booleans so frontend
            templates don't need to know the enum vocabulary.
        """
        moment = now or datetime.now(tz=timezone.utc)

        trial: TrialInfo | None = None
        if sub.trial_started_at is not None and sub.trial_ends_at is not None:
            remaining_seconds = (sub.trial_ends_at - moment).total_seconds()
            days_remaining = (
                0 if remaining_seconds <= 0 else math.ceil(remaining_seconds / 86400)
            )
            trial = TrialInfo(
                started_at=sub.trial_started_at,
                ends_at=sub.trial_ends_at,
                days_remaining=days_remaining,
            )

        extra_seat_cost = (
            plan.pricing.extra_seat_annual_usd
            if sub.billing_cycle == "annual"
            else plan.pricing.extra_seat_monthly_usd
        )

        usage_rows: list[UsageRow] = []
        for resource, current in usage_snapshot.items():
            cap_value = getattr(plan.caps, resource, 0)
            usage_rows.append(
                UsageRow(
                    resource=resource,
                    current=current,
                    cap=cap_value,
                    is_unlimited=cap_value == -1,
                )
            )

        return cls(
            id=sub.id,
            plan=PlanShort(
                code=plan.code,
                name=plan.name,
                monthly_bundle_usd=plan.pricing.monthly_bundle_usd,
                annual_bundle_usd=plan.pricing.annual_bundle_usd,
                extra_seat_monthly_usd=plan.pricing.extra_seat_monthly_usd,
                extra_seat_annual_usd=plan.pricing.extra_seat_annual_usd,
                included_seats=plan.pricing.included_seats,
            ),
            status=sub.status,
            billing_cycle=sub.billing_cycle,
            trial=trial,
            period=PeriodInfo(
                start=sub.current_period_start,
                end=sub.current_period_end,
                renews_at=sub.current_period_end,
            ),
            seats=SeatsInfo(
                included=plan.pricing.included_seats,
                purchased=sub.seats_purchased,
                in_use=seats_in_use,
                extra_seat_cost_per_period_usd=extra_seat_cost,
            ),
            usage=usage_rows,
            read_only=sub.status == "read_only",
            archived=sub.status == "archived",
            cancelled=sub.status == "cancelled",
            stripe_customer_id=sub.stripe_customer_id,
            stripe_subscription_id=sub.stripe_subscription_id,
        )
