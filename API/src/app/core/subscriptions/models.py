"""SQLAlchemy model for per-org subscription state.

One row tracks each org's current and historical billing state. The
invariant — exactly one *active* subscription per org — is enforced by
a Postgres partial unique index (`subscriptions_active_per_org_uq`)
applied via the migration; `archived` and `cancelled` rows are history
and may stack.

The `plan_code` column references a code in `core/subscriptions/plans.yaml`
(see Step 1's plan registry). It is intentionally NOT a foreign key —
plans live in YAML, not in the database. The entitlement service
(Step 3) validates the code at read time and raises if it is unknown,
so consumers can rely on the model returning a known code.

Stripe-side identifiers (`stripe_customer_id`, `stripe_subscription_id`)
remain NULL during the trial and only populate after Step 13's webhook
handler processes the first paid `checkout.session.completed` event.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


# Canonical status values. The CHECK constraint at the DB level mirrors
# this tuple; the entitlement service uses the same list.
SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "trialing",
    "active",
    "past_due",
    "read_only",
    "archived",
    "cancelled",
)

# Statuses that count as "the org's currently active subscription."
# Used by the partial unique index AND by `get_active_subscription`.
ACTIVE_STATUSES: tuple[str, ...] = (
    "trialing",
    "active",
    "past_due",
    "read_only",
)

BILLING_CYCLES: tuple[str, ...] = ("monthly", "annual")


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Subscription(Base, TenantScoped):
    """One subscription row per org per lifecycle.

    The combination (`status`, `trial_*`, `current_period_*`, `*_at`)
    encodes the full state machine; the lifecycle service (Step 6)
    advances rows through it.
    """

    __tablename__ = "tbl_subscriptions"

    # SQLAlchemy-level constraints. The Alembic migration *also* declares
    # the partial unique index as raw SQL so production gets it; this
    # declaration here ensures `Base.metadata.create_all` (used by
    # `tests/conftest.py`) reproduces the same shape in the test DB.
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(SUBSCRIPTION_STATUSES)})",
            name="subscriptions_status_check",
        ),
        CheckConstraint(
            f"billing_cycle IN ({_in_clause(BILLING_CYCLES)})",
            name="subscriptions_billing_cycle_check",
        ),
        CheckConstraint(
            "seats_purchased >= 1",
            name="subscriptions_seats_positive_check",
        ),
        # Partial unique index: exactly one ACTIVE subscription per org.
        # `archived` and `cancelled` rows are history and may stack.
        Index(
            "subscriptions_active_per_org_uq",
            "org_id",
            unique=True,
            postgresql_where=text(
                f"status IN ({_in_clause(ACTIVE_STATUSES)})"
            ),
        ),
    )

    # Convenience aliases re-exported for service / test code so it
    # does not need to import the constants separately.
    STATUSES: ClassVar[tuple[str, ...]] = SUBSCRIPTION_STATUSES
    ACTIVE_STATUSES: ClassVar[tuple[str, ...]] = ACTIVE_STATUSES
    BILLING_CYCLES: ClassVar[tuple[str, ...]] = BILLING_CYCLES

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # `org_id` comes from TenantScoped — FK to organizations.id with
    # ondelete=RESTRICT (keep history if the org row is somehow purged).

    plan_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        server_default=text("'monthly'"),
    )
    seats_purchased: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )

    trial_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    read_only_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Step 8 — scheduled change at next period boundary.
    # Populated by the plan-change API when an Owner requests a
    # downgrade (lower tier, annual→monthly, or seat reduction) so the
    # lifecycle task can flip the row at `current_period_end`. All three
    # stay NULL until a downgrade is scheduled and clear back to NULL
    # once `apply_scheduled_change_if_due` lands the change.
    next_plan_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    next_billing_cycle: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    next_seats: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Step 12 — most recent Stripe Checkout Session ID created for the
    # org. Set when an upgrade flow opens hosted checkout; cleared by
    # the Step 13 webhook on `checkout.session.completed` or
    # `checkout.session.expired`. A non-null value means there is a
    # pending payment intent the operator can re-share with the user.
    pending_checkout_session_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    # Dedup ledger for one-shot reminder emails the trial-lifecycle
    # task emits (e.g. `trial_ending_soon`). Each entry is
    # `{<reminder_key>: true}`; absence means "not sent." JSONB instead
    # of a separate table because the taxonomy is tiny and lives 1:1
    # with the subscription. See `lifecycle.fire_due_reminders`.
    reminders_sent: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<Subscription org={self.org_id} "
            f"plan={self.plan_code} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# Usage counters
# ---------------------------------------------------------------------------

USAGE_PERIOD_KINDS: tuple[str, ...] = ("lifetime", "monthly", "daily")


class UsageCounter(Base, TenantScoped):
    """Denormalised per-org consumption counter for a single capped resource.

    One row per `(org_id, resource, period_start)` tuple. The
    `period_start` axis lets us bucket counts:

      - `lifetime` resources (contacts, storage_mb) carry a single row
        per org whose `period_start` is the subscription creation date
        and whose `period_end` is the far-future sentinel
        (`9999-12-31`).
      - `monthly` resources (leads_per_month, automation_runs_per_month,
        email_sends_per_month, etc.) carry one row per billing period.
        The rollover Celery task inserts a fresh zeroed row at each
        `current_period_end`.
      - `daily` resources (`api_calls_per_day`) carry one row per UTC
        day; the daily-reset task creates the next day's row at
        midnight UTC.

    The `value` column is `BIGINT` so a busy Enterprise org can do
    100k+ API calls/day without overflow.

    `increment` (in `usage_service.py`) is the only write path; it uses
    a Postgres `INSERT ... ON CONFLICT DO UPDATE` against the
    `(org_id, resource, period_start)` unique index, so concurrent
    bumps remain race-safe.
    """

    __tablename__ = "tbl_usage_counters"
    __table_args__ = (
        CheckConstraint(
            "period_kind IN ('lifetime', 'monthly', 'daily')",
            name="usage_counters_period_kind_check",
        ),
        UniqueConstraint(
            "org_id",
            "resource",
            "period_start",
            name="usage_counters_org_resource_period_uq",
        ),
        Index(
            "ix_usage_counters_lookup",
            "org_id",
            "resource",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # `org_id` comes from TenantScoped.

    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    period_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<UsageCounter org={self.org_id} "
            f"resource={self.resource} value={self.value}>"
        )


# ---------------------------------------------------------------------------
# Step 13 — Stripe webhook ledger + invoice mirror
# ---------------------------------------------------------------------------


INVOICE_STATUSES: tuple[str, ...] = (
    "paid", "open", "void", "uncollectible", "draft",
)


class SubscriptionInvoice(Base, TenantScoped):
    """Local mirror of a Stripe invoice.

    Step 13's `invoice.*` webhook handlers upsert into this table on
    `stripe_invoice_id`. The billing-settings page (Step 16) reads
    this list to render invoice history; clicking through to
    `hosted_invoice_url` or `pdf_url` hands the user back to
    Stripe-hosted UI for the actual document.

    `subscription_id` is FK-enforced so an invoice cannot exist for a
    purged subscription row; if `checkout.session.completed` and
    `invoice.paid` arrive out of order, the invoice handler returns
    500 (Stripe retries) until the checkout handler has run first.
    """

    __tablename__ = "tbl_subscription_invoices"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(INVOICE_STATUSES)})",
            name="subscription_invoices_status_check",
        ),
        UniqueConstraint(
            "stripe_invoice_id",
            name="subscription_invoices_stripe_id_uq",
        ),
        Index(
            "ix_subscription_invoices_subscription_id",
            "subscription_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # `org_id` comes from TenantScoped.

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    stripe_invoice_id: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_due_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'USD'"),
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hosted_invoice_url: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class StripeWebhookEvent(Base):
    """Idempotency ledger for Stripe webhook delivery.

    Primary key = `stripe_event_id` so an `INSERT … ON CONFLICT DO
    NOTHING` is the dedup primitive — if the row already exists, the
    handler short-circuits and the route returns 200 so Stripe stops
    retrying.

    `payload` stores the raw event for replay / debug. `error` is
    populated when the handler raises; the row stays unprocessed
    (processed_at = NULL) so a future retry can re-run the handler.

    No `org_id` — events may arrive before we have resolved the
    target org (e.g. raw account-level events). This table is
    administrative, not tenant-scoped, so RLS is off.
    """

    __tablename__ = "tbl_stripe_webhook_events"

    stripe_event_id: Mapped[str] = mapped_column(
        Text, primary_key=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return (
            f"<StripeWebhookEvent id={self.stripe_event_id} "
            f"type={self.event_type} processed={self.processed_at is not None}>"
        )
