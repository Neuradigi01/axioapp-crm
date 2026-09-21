"""Email-reputation persistence — ``tbl_organization_email_reputation``.

Step 2 of ``tasks/email-reputation-warmup/``.

Persists the per-envelope reputation state that survives across Redis
restarts (warmup stage, block-until stamp, daily sent counter, daily
reset). 24h rolling counters live in Redis (Step 2's counters.py) —
this table is the source of truth for state transitions the send-gate
reads on every dispatch.

Column shape follows the README's spec verbatim. Uniqueness:

* ``platform_from`` rows: at most ONE per org (``domain_id`` is NULL).
* ``own_domain`` rows: at most one per ``(org_id, domain_id)``.

Enforced by two partial unique indexes — Postgres' default UNIQUE
treats NULL as distinct, which would let a caller insert two
platform_from rows for the same org. Partial indexes sidestep that
with no ``NULLS NOT DISTINCT`` compat cost on future Postgres upgrades.

Not wired to any code path yet — this migration is purely additive.
Steps 3–7 add the events webhook, evaluators, send-gate, and dashboard
on top.

Revision ID: 0235_email_reputation
Revises:     0234_forwarded_address
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0235_email_reputation"
down_revision: str | None = "0234_forwarded_address"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_organization_email_reputation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("envelope_type", sa.String(16), nullable=False),
        sa.Column(
            "domain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organization_email_domains.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "warmup_stage",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "warmup_stage_earned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "warmup_stage_current_sent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "daily_sent_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("daily_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "bounce_count_24h",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "complaint_count_24h",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "delivered_count_24h",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "reputation_state",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'ok'"),
        ),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "envelope_type IN ('platform_from', 'own_domain')",
            name="ck_email_reputation_envelope_enum",
        ),
        sa.CheckConstraint(
            "reputation_state IN ('ok', 'warned', 'blocked')",
            name="ck_email_reputation_state_enum",
        ),
        # ``platform_from`` rows carry NULL ``domain_id``; ``own_domain``
        # rows carry the domain FK. Enforced pair-wise so a caller can't
        # accidentally save an ``own_domain`` row with no domain FK.
        sa.CheckConstraint(
            "(envelope_type = 'platform_from' AND domain_id IS NULL) "
            "OR (envelope_type = 'own_domain' AND domain_id IS NOT NULL)",
            name="ck_email_reputation_envelope_domain_shape",
        ),
        sa.CheckConstraint(
            "warmup_stage >= 0",
            name="ck_email_reputation_warmup_stage_nonneg",
        ),
    )

    # Composite lookup index — send-gate + events-webhook both hit
    # ``(org_id, envelope_type)`` to resolve the row.
    op.create_index(
        "ix_email_reputation_org_envelope",
        "tbl_organization_email_reputation",
        ["org_id", "envelope_type"],
    )
    # Sweeper index — hourly beat scans blocked rows whose window
    # has elapsed to flip them back to 'ok'. Partial keeps the index
    # tiny (blocked rows are the exception).
    op.create_index(
        "ix_email_reputation_state_blocked_until",
        "tbl_organization_email_reputation",
        ["reputation_state", "blocked_until"],
        postgresql_where=sa.text("reputation_state = 'blocked'"),
    )

    # Uniqueness — two partial unique indexes since Postgres' default
    # UNIQUE treats NULL as distinct (would allow two platform_from
    # rows for the same org). Splitting by envelope_type dodges the
    # NULL-distinct surprise without needing NULLS NOT DISTINCT (which
    # would tie us to PG15+).
    op.create_index(
        "uq_email_reputation_platform_from",
        "tbl_organization_email_reputation",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("envelope_type = 'platform_from'"),
    )
    op.create_index(
        "uq_email_reputation_own_domain",
        "tbl_organization_email_reputation",
        ["org_id", "domain_id"],
        unique=True,
        postgresql_where=sa.text("envelope_type = 'own_domain'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_reputation_own_domain",
        table_name="tbl_organization_email_reputation",
    )
    op.drop_index(
        "uq_email_reputation_platform_from",
        table_name="tbl_organization_email_reputation",
    )
    op.drop_index(
        "ix_email_reputation_state_blocked_until",
        table_name="tbl_organization_email_reputation",
    )
    op.drop_index(
        "ix_email_reputation_org_envelope",
        table_name="tbl_organization_email_reputation",
    )
    op.drop_table("tbl_organization_email_reputation")
