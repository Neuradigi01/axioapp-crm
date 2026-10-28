"""subscriptions table — per-org billing state.

One row per org per lifecycle. Tracks plan / status / trial window /
seat count / billing cycle / Stripe linkage. The active-subscription
invariant — exactly one row per org whose status is NOT in
{archived, cancelled} — is enforced by a Postgres partial unique
index. Status and billing_cycle are constrained by CHECK clauses.

RLS uses the standard `apply_rls` helper (`org_id = current_setting(
'app.org_id', true)::uuid`), matching every other tenant-scoped table.

Backfill: each existing organization gets one row inserted with
`plan_code='trial'`, `status='trialing'`, a fresh 14-day trial window
starting at migration time, and `seats_purchased=3` (the trial bundle).
This is a pragmatic, non-destructive default — it does not imply we
charged anyone, and existing orgs continue to work without code
changes. They land on a 14-day clock; the lifecycle service (Step 6)
will advance them after expiry.

Revision ID: 0074_subscriptions_table
Revises:     0073_catalog_image_url
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0074_subscriptions_table"
down_revision: Union[str, None] = "0073_catalog_image_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with `core/subscriptions/models.py` constants. Centralised
# here so the migration is self-contained (alembic env should be free of
# project-runtime imports beyond what's already there).
_STATUSES = ("trialing", "active", "past_due", "read_only", "archived", "cancelled")
_ACTIVE_STATUSES = ("trialing", "active", "past_due", "read_only")
_BILLING_CYCLES = ("monthly", "annual")


def _in_clause(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "billing_cycle",
            sa.String(length=8),
            server_default=sa.text("'monthly'"),
            nullable=False,
        ),
        sa.Column(
            "seats_purchased",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_period_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "current_period_end",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("read_only_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=64), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            f"status IN ({_in_clause(_STATUSES)})",
            name="subscriptions_status_check",
        ),
        sa.CheckConstraint(
            f"billing_cycle IN ({_in_clause(_BILLING_CYCLES)})",
            name="subscriptions_billing_cycle_check",
        ),
        sa.CheckConstraint(
            "seats_purchased >= 1",
            name="subscriptions_seats_positive_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Hot-path lookup index — every subscription read filters by org_id.
    # `TenantScoped`'s `index=True` produces the `ix_subscriptions_org_id`
    # name when `create_all` is used; declare it explicitly here so the
    # production schema matches.
    op.create_index(
        "ix_subscriptions_org_id", "subscriptions", ["org_id"]
    )
    op.create_index(
        "ix_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
    )
    op.create_index(
        "ix_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
    )

    # Partial unique: one active subscription per org. Archived /
    # cancelled rows are history and may stack — they are excluded
    # from the index predicate.
    op.execute(
        f"""
        CREATE UNIQUE INDEX subscriptions_active_per_org_uq
        ON subscriptions (org_id)
        WHERE status IN ({_in_clause(_ACTIVE_STATUSES)})
        """
    )

    apply_rls("subscriptions")

    # Backfill: every existing org gets a fresh 14-day trial starting
    # now. `seats_purchased = 3` matches the trial plan's included_seats
    # from `plans.yaml`.
    op.execute(
        """
        INSERT INTO subscriptions (
            org_id,
            plan_code,
            status,
            billing_cycle,
            seats_purchased,
            trial_started_at,
            trial_ends_at,
            current_period_start,
            current_period_end
        )
        SELECT
            o.id,
            'trial',
            'trialing',
            'monthly',
            3,
            now(),
            now() + interval '14 days',
            now(),
            now() + interval '14 days'
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM subscriptions s WHERE s.org_id = o.id
        )
        """
    )


def downgrade() -> None:
    drop_rls("subscriptions")
    op.execute("DROP INDEX IF EXISTS subscriptions_active_per_org_uq")
    op.drop_index(
        "ix_subscriptions_stripe_subscription_id",
        table_name="subscriptions",
    )
    op.drop_index(
        "ix_subscriptions_stripe_customer_id",
        table_name="subscriptions",
    )
    op.drop_index("ix_subscriptions_org_id", table_name="subscriptions")
    op.drop_table("subscriptions")
