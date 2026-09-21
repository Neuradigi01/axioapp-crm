"""Track 5 Step 1 — ``tbl_email_quarantine`` + ``tbl_email_filter_rules``.

Two tables that gate the shipped Mailgun-inbound pipeline:

  * :data:`tbl_email_quarantine` — held-mail rows for suspicious
    inbound (size, blocked-sender, rate-capped, spam-verdict, virus-
    verdict). Operator releases → replays through ``_persist_inbound_email``;
    discards → row + on-disk payload deleted. Auto-purged after 30 d.

  * :data:`tbl_email_filter_rules` — per-org allow / block rules
    matched on address, domain, or contact flag. Consulted by the
    extended gate chain (Step 4) before any of the shipped SPF/DKIM
    logic runs. Cap of 500 rules per org.

Both tables are ``tbl_``-prefixed and carry ``org_id`` per rule 2.
Quarantine cascades from the endpoint FK; filter rules cascade from
either the endpoint FK (endpoint-scoped) or stay attached to the org
(``endpoint_id IS NULL``, org-wide default).

Revision ID: 0236_email_quarantine
Revises:     0235_email_reputation
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0236_email_quarantine"
down_revision: str | None = "0235_email_reputation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tbl_email_quarantine
    # ------------------------------------------------------------------
    op.create_table(
        "tbl_email_quarantine",
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
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mailgun_delivery_id", sa.String(64), nullable=True),
        sa.Column("from_address", sa.String(255), nullable=False),
        sa.Column("from_display_name", sa.String(255), nullable=True),
        sa.Column("to_recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(1024), nullable=True),
        sa.Column("body_snippet", sa.Text(), nullable=True),
        sa.Column(
            "attachment_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column(
            "reason_detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("payload_path", sa.String(512), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'held'"),
        ),
        sa.Column(
            "blocked_release",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "held_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "reason_code IN ('size_exceeded', 'blocked_sender', 'rate_capped', "
            "'spam_verdict', 'virus_verdict')",
            name="ck_email_quarantine_reason_code",
        ),
        sa.CheckConstraint(
            "status IN ('held', 'released', 'discarded', 'auto_purged')",
            name="ck_email_quarantine_status",
        ),
        # UNIQUE(mailgun_delivery_id) — same delivery only quarantines
        # once per org across restarts. Partial so NULL delivery IDs
        # (system-actor drops) don't collide.
        sa.UniqueConstraint(
            "mailgun_delivery_id",
            name="uq_email_quarantine_mailgun_delivery_id",
        ),
    )
    op.create_index(
        "ix_email_quarantine_org_status_held",
        "tbl_email_quarantine",
        ["org_id", "status", "held_at"],
    )
    op.create_index(
        "ix_email_quarantine_reason",
        "tbl_email_quarantine",
        ["reason_code"],
    )
    op.create_index(
        "ix_email_quarantine_held_at_status",
        "tbl_email_quarantine",
        ["held_at", "status"],
        postgresql_where=sa.text("status = 'held'"),
    )

    # ------------------------------------------------------------------
    # tbl_email_filter_rules
    # ------------------------------------------------------------------
    op.create_table(
        "tbl_email_filter_rules",
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
        ),
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rule_type", sa.String(16), nullable=False),
        sa.Column("match_kind", sa.String(16), nullable=False),
        sa.Column("match_value", sa.String(255), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "rule_type IN ('allow', 'block')",
            name="ck_email_filter_rules_rule_type",
        ),
        sa.CheckConstraint(
            "match_kind IN ('email_address', 'email_domain', 'contact_flag')",
            name="ck_email_filter_rules_match_kind",
        ),
        # Duplicate-guard: same (org, endpoint, type, kind, value) can
        # only exist once. Endpoint-null (org-wide) treated as its own
        # bucket via COALESCE — Postgres's UNIQUE-with-nulls semantics
        # would otherwise let duplicate rows in.
        sa.Index(
            "uq_email_filter_rules_dedupe",
            "org_id",
            sa.text("COALESCE(endpoint_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "rule_type",
            "match_kind",
            "match_value",
            unique=True,
        ),
    )
    op.create_index(
        "ix_email_filter_rules_org_endpoint",
        "tbl_email_filter_rules",
        ["org_id", "endpoint_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_filter_rules_org_endpoint",
        table_name="tbl_email_filter_rules",
    )
    op.drop_index(
        "uq_email_filter_rules_dedupe",
        table_name="tbl_email_filter_rules",
    )
    op.drop_table("tbl_email_filter_rules")
    op.drop_index(
        "ix_email_quarantine_held_at_status",
        table_name="tbl_email_quarantine",
    )
    op.drop_index("ix_email_quarantine_reason", table_name="tbl_email_quarantine")
    op.drop_index(
        "ix_email_quarantine_org_status_held",
        table_name="tbl_email_quarantine",
    )
    op.drop_table("tbl_email_quarantine")
