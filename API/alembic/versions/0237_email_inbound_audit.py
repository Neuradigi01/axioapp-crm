"""Track 6 Step 1 — ``tbl_email_inbound_deliveries``.

Append-only audit trail of every Mailgun inbound webhook receipt.
90-day retention. Metadata only — no message content.

**Documented deviation from CLAUDE.md Rule 2 (`org_id` on every table):**
this table is deliberately **system-level** and does NOT carry an
``org_id`` column. Many outcomes (``signature_rejected``,
``replay_rejected``, ``timestamp_rejected``, ``size_rejected_before_download``)
happen BEFORE we've resolved the token → sender → org, so we cannot
attribute those rows to any tenant. Precedent: ``tbl_email_inbound_dlq``
(mailgun-inbound track) makes the same trade-off. Platform admins are
the only role with visibility.

Revision ID: 0237_email_inbound_audit
Revises:     0236_email_quarantine
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0237_email_inbound_audit"
down_revision: str | None = "0236_email_quarantine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_email_inbound_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mailgun_delivery_id", sa.String(64), nullable=True),
        sa.Column("mailgun_message_id", sa.String(255), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("signature_status", sa.String(16), nullable=False),
        sa.Column("replay_status", sa.String(16), nullable=False),
        sa.Column("timestamp_status", sa.String(16), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=True),
        sa.Column("sender", sa.String(255), nullable=True),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column(
            "outcome_detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("client_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('enqueued', 'signature_rejected', 'replay_rejected', "
            "'timestamp_rejected', 'size_rejected_before_download')",
            name="ck_email_inbound_deliveries_outcome",
        ),
    )
    # Chronological reads for the audit log tab.
    op.create_index(
        "ix_email_inbound_deliveries_received_at",
        "tbl_email_inbound_deliveries",
        [sa.text("received_at DESC")],
    )
    # Delivery-id lookup (used by cross-referencing quarantine rows).
    op.create_index(
        "ix_email_inbound_deliveries_delivery_id",
        "tbl_email_inbound_deliveries",
        ["mailgun_delivery_id"],
        postgresql_where=sa.text("mailgun_delivery_id IS NOT NULL"),
    )
    # Outcome filter on the tab.
    op.create_index(
        "ix_email_inbound_deliveries_outcome_at",
        "tbl_email_inbound_deliveries",
        ["outcome", sa.text("received_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_inbound_deliveries_outcome_at",
        table_name="tbl_email_inbound_deliveries",
    )
    op.drop_index(
        "ix_email_inbound_deliveries_delivery_id",
        table_name="tbl_email_inbound_deliveries",
    )
    op.drop_index(
        "ix_email_inbound_deliveries_received_at",
        table_name="tbl_email_inbound_deliveries",
    )
    op.drop_table("tbl_email_inbound_deliveries")
