"""usage_counters table — denormalised per-org consumption counters.

One row per `(org_id, resource, period_start)` tuple. The write path is
`usage_service.increment(...)` which does an `INSERT ... ON CONFLICT
DO UPDATE` against the unique index defined here, so concurrent bumps
remain race-safe without an application-level lock.

`period_kind` is `'lifetime' | 'monthly' | 'daily'`:
  - `lifetime` rows (contacts, storage_mb) live for the duration of the
    subscription. `period_start` is the subscription `created_at`;
    `period_end` is the far-future sentinel `9999-12-31` so the unique
    index treats lifetime windows distinctly from period-aligned ones.
  - `monthly` rows (leads/automation/email/sms per month, form
    submissions per month) are reset at each `current_period_end` by
    the rollover Celery task.
  - `daily` rows (`api_calls_per_day`) are reset at 00:00 UTC by the
    daily-reset Celery task.

RLS uses the standard `apply_rls` helper (org-scoped via
`current_setting('app.org_id', true)::uuid`).

Revision ID: 0075_usage_counters_table
Revises:     0074_subscriptions_table
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0075_usage_counters_table"
down_revision: Union[str, None] = "0074_subscriptions_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_counters",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("period_kind", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "value",
            sa.BigInteger(),
            server_default=sa.text("0"),
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
            "period_kind IN ('lifetime', 'monthly', 'daily')",
            name="usage_counters_period_kind_check",
        ),
        sa.UniqueConstraint(
            "org_id",
            "resource",
            "period_start",
            name="usage_counters_org_resource_period_uq",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # `TenantScoped`'s `index=True` produces `ix_usage_counters_org_id` when
    # `create_all` is used in tests; declare it explicitly here so the
    # production schema matches.
    op.create_index(
        "ix_usage_counters_org_id", "usage_counters", ["org_id"]
    )
    # Hot-path read predicate: every `get(org_id, resource)` filters on
    # `(org_id, resource)` and then by `period_start`. The unique index
    # serves the increment write; this composite serves the read.
    op.create_index(
        "ix_usage_counters_lookup",
        "usage_counters",
        ["org_id", "resource"],
    )

    apply_rls("usage_counters")


def downgrade() -> None:
    drop_rls("usage_counters")
    op.drop_index("ix_usage_counters_lookup", table_name="usage_counters")
    op.drop_index("ix_usage_counters_org_id", table_name="usage_counters")
    op.drop_table("usage_counters")
