"""Pydantic schemas for the subscription model.

Only the read shape lands in this step — write-side payloads (plan
change, seat change, cancellation) are introduced in Steps 8-10 when
the corresponding endpoints land.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
