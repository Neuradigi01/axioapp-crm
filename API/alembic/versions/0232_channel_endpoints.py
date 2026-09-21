"""Channel-endpoints abstraction — ``tbl_channel_endpoints`` +
``tbl_email_endpoint_details`` + backfill from shipped inbound paths.

Step 1 of ``tasks/email-endpoint-abstraction/``.

Two new tables collapse the three per-provider inbound-token stores
we grew organically (``tbl_email_smtp_senders.inbound_token`` for
mailgun reply-capture, native OAuth sync for Gmail/Microsoft, nothing
for the coming forwarded-address flow) into a single endpoint model
that Tracks 2–6 all sit on.

Behaviour change: **zero.** Nothing reads the new tables yet. The
legacy ``inbound_token`` column on ``tbl_email_smtp_senders`` is
deliberately preserved — its removal is a follow-up track after every
downstream caller migrates to ``EmailEndpointDetails.reply_token``.

Backfill is idempotent — ``WHERE NOT EXISTS`` guards on both INSERTs.
Partial-crash retry regenerates only unfilled rows.

Revision ID: 0232_channel_endpoints
Revises:     0231_any_sender_default
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0232_channel_endpoints"
down_revision: str | None = "0231_any_sender_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tbl_channel_endpoints
    # ------------------------------------------------------------------
    op.create_table(
        "tbl_channel_endpoints",
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
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("endpoint_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.String(64), nullable=True),
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
            "channel IN ('email')",
            name="ck_channel_endpoints_channel_enum",
        ),
    )
    op.create_index(
        "ix_channel_endpoints_org_id",
        "tbl_channel_endpoints",
        ["org_id"],
    )
    op.create_index(
        "ix_channel_endpoints_org_channel_type",
        "tbl_channel_endpoints",
        ["org_id", "channel", "endpoint_type"],
    )

    # ------------------------------------------------------------------
    # tbl_email_endpoint_details
    # ------------------------------------------------------------------
    # 1:1 with tbl_channel_endpoints via endpoint_id PK+FK. Own org_id
    # column for RLS defense-in-depth. Track 2 will add FK from
    # domain_id → tbl_organization_email_domains.id — kept unconstrained
    # here to avoid a cyclic dependency in migration ordering.
    op.create_table(
        "tbl_email_endpoint_details",
        sa.Column(
            "endpoint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("forwarding_token", sa.String(32), nullable=True),
        sa.Column("reply_token", sa.String(32), nullable=True),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "smtp_sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_email_smtp_senders.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "oauth_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_email_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "forwarding_token",
            name="uq_email_endpoint_details_forwarding_token",
        ),
        sa.UniqueConstraint(
            "reply_token",
            name="uq_email_endpoint_details_reply_token",
        ),
        sa.UniqueConstraint(
            "smtp_sender_id",
            name="uq_email_endpoint_details_smtp_sender",
        ),
        sa.UniqueConstraint(
            "oauth_account_id",
            name="uq_email_endpoint_details_oauth_account",
        ),
    )
    op.create_index(
        "ix_email_endpoint_details_org_id",
        "tbl_email_endpoint_details",
        ["org_id"],
    )
    op.create_index(
        "ix_email_endpoint_details_domain_id",
        "tbl_email_endpoint_details",
        ["domain_id"],
        postgresql_where=sa.text("domain_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # Backfill: SMTP senders with mailgun-inbound reply-capture tokens.
    #
    # Every shipped SMTP sender that carries a non-null inbound_token
    # gets one endpoint row (type=smtp_reply_capture) + one details row
    # (reply_token = inbound_token, smtp_sender_id FK).
    #
    # Idempotent: WHERE NOT EXISTS guards on both INSERTs. Partial-crash
    # retry regenerates only unfilled rows.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO tbl_channel_endpoints
            (id, org_id, channel, endpoint_type, label, is_active, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            s.org_id,
            'email',
            'smtp_reply_capture',
            s.from_address,
            true,
            now(),
            now()
        FROM tbl_email_smtp_senders s
        WHERE s.inbound_token IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
                FROM tbl_email_endpoint_details d
               WHERE d.smtp_sender_id = s.id
          )
        """
    )
    op.execute(
        """
        INSERT INTO tbl_email_endpoint_details
            (endpoint_id, org_id, reply_token, smtp_sender_id)
        SELECT
            e.id,
            s.org_id,
            s.inbound_token,
            s.id
        FROM tbl_email_smtp_senders s
        JOIN tbl_channel_endpoints e
          ON e.org_id = s.org_id
         AND e.channel = 'email'
         AND e.endpoint_type = 'smtp_reply_capture'
         AND e.label = s.from_address
        WHERE s.inbound_token IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
                FROM tbl_email_endpoint_details d
               WHERE d.smtp_sender_id = s.id
          )
        """
    )

    # ------------------------------------------------------------------
    # Backfill: Gmail + Microsoft OAuth mailboxes.
    #
    # One endpoint row per connected OAuth account (type=oauth_mailbox).
    # Details row's oauth_account_id FK carries the linkage; no tokens
    # (OAuth doesn't need forwarding/reply tokens — provider sync
    # returns replies natively).
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO tbl_channel_endpoints
            (id, org_id, channel, endpoint_type, label, is_active, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            a.org_id,
            'email',
            'oauth_mailbox',
            a.email_address,
            true,
            now(),
            now()
        FROM tbl_email_accounts a
        WHERE NOT EXISTS (
              SELECT 1
                FROM tbl_email_endpoint_details d
               WHERE d.oauth_account_id = a.id
          )
        """
    )
    op.execute(
        """
        INSERT INTO tbl_email_endpoint_details
            (endpoint_id, org_id, oauth_account_id)
        SELECT
            e.id,
            a.org_id,
            a.id
        FROM tbl_email_accounts a
        JOIN tbl_channel_endpoints e
          ON e.org_id = a.org_id
         AND e.channel = 'email'
         AND e.endpoint_type = 'oauth_mailbox'
         AND e.label = a.email_address
        WHERE NOT EXISTS (
              SELECT 1
                FROM tbl_email_endpoint_details d
               WHERE d.oauth_account_id = a.id
          )
        """
    )


def downgrade() -> None:
    # Drop details first (references endpoints via FK), then endpoints.
    # Legacy tbl_email_smtp_senders.inbound_token is untouched — no
    # data lost by rolling back this migration.
    op.drop_index(
        "ix_email_endpoint_details_domain_id",
        table_name="tbl_email_endpoint_details",
    )
    op.drop_index(
        "ix_email_endpoint_details_org_id",
        table_name="tbl_email_endpoint_details",
    )
    op.drop_table("tbl_email_endpoint_details")
    op.drop_index(
        "ix_channel_endpoints_org_channel_type",
        table_name="tbl_channel_endpoints",
    )
    op.drop_index(
        "ix_channel_endpoints_org_id",
        table_name="tbl_channel_endpoints",
    )
    op.drop_table("tbl_channel_endpoints")
