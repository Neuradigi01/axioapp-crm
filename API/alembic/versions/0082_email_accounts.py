"""email_accounts — per-user connected mailbox model + RLS.

One row per `(user_id, provider, external_account_id)`. Tokens land
as Fernet ciphertext (`access_token_enc`, `refresh_token_enc`,
both TEXT — Fernet output is url-safe-base64, matches the
`integrations` table convention) under the existing
`INTEGRATIONS_ENCRYPTION_KEY`. A DB dump alone leaks no usable
OAuth credentials.

Two Postgres enums:
  - `email_account_provider`: `gmail` | `microsoft`.
  - `email_account_sync_state`: `pending` | `backfilling` | `live`
    | `error` | `disconnected`.

`user_id` and the audit columns (`disconnected_by`) are plain UUIDs
with no FK to `users(id)` per the post-0037 convention — the legacy
`users` table is on soak; the live user identity is `legacy_uuid`
(carried by `tbl_user_login.legacy_uuid`).

Tenant isolation: standard `apply_rls("email_accounts")` policy on
`org_id`. The sync daemon (Step 4) and provider adapters (Step 2/3)
open sessions inside an existing tenant context — RLS authorises
every read/write.

Revision ID: 0082_email_accounts
Revises: 0081_owner_billing_manage_grant
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0082_email_accounts"
down_revision: Union[str, None] = "0081_owner_billing_manage_grant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `create_type=False` — we own the lifecycle via the DO blocks below
# so a stray enum from an aborted earlier run does not blow up
# `op.create_table`'s implicit CREATE TYPE.
_PROVIDER_ENUM = PgEnum(
    "gmail",
    "microsoft",
    name="email_account_provider",
    create_type=False,
)
_SYNC_STATE_ENUM = PgEnum(
    "pending",
    "backfilling",
    "live",
    "error",
    "disconnected",
    name="email_account_sync_state",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE email_account_provider AS ENUM (
                'gmail',
                'microsoft'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE email_account_sync_state AS ENUM (
                'pending',
                'backfilling',
                'live',
                'error',
                'disconnected'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "email_accounts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        # Plain UUID (no FK) per post-0037 convention. The rep's
        # legacy_uuid on tbl_user_login.
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", _PROVIDER_ENUM, nullable=False),
        # Gmail: the message-owner address ('me' resolved at OAuth).
        # Graph: the AAD object id.
        sa.Column("external_account_id", sa.Text(), nullable=False),
        # Denormalised for sync-time matching against contacts.email.
        sa.Column("email_address", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        # Fernet ciphertexts. NULL when sync_state='disconnected' —
        # the row stays so the connect/disconnect history survives
        # across reconnections.
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        # Postgres TEXT[]: the granted OAuth scopes. Lets the UI
        # surface "Connected with X scopes" + detect scope-set
        # narrowing on reconnect.
        sa.Column(
            "scopes_granted",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        # Gmail historyId or Graph deltaToken.
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column(
            "sync_state",
            _SYNC_STATE_ENUM,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        # Daily send governor — Step 5 enforces soft/hard caps via
        # an atomic UPDATE on these columns. Lands here so Step 5
        # doesn't need a follow-up migration.
        sa.Column(
            "daily_sent_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "daily_sent_reset_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "disconnected_at", sa.DateTime(timezone=True), nullable=True
        ),
        # No FK — post-0037 convention.
        sa.Column(
            "disconnected_by", UUID(as_uuid=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # Stops a single user from connecting the same external
        # account twice (e.g. running the OAuth flow concurrently).
        # A user CAN connect both a Gmail and a Microsoft account,
        # or two distinct Gmail accounts.
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "external_account_id",
            name="uq_email_accounts_user_provider_external",
        ),
    )

    # Lookups for the sync daemon: "give me every live account that's
    # due a poll." Compound on (org, sync_state) because the daemon's
    # tick query is also scoped per tenant via RLS.
    op.create_index(
        "ix_email_accounts_org_sync_state",
        "email_accounts",
        ["org_id", "sync_state"],
    )
    # Reverse-lookup at inbound-sync time: match an email's `from/to`
    # header against a connected mailbox in the org. Lower() because
    # email addresses are case-insensitive per RFC 5321.
    op.create_index(
        "ix_email_accounts_org_email_lower",
        "email_accounts",
        ["org_id", sa.text("lower(email_address)")],
    )

    apply_rls("email_accounts")


def downgrade() -> None:
    drop_rls("email_accounts")
    op.drop_index(
        "ix_email_accounts_org_email_lower", table_name="email_accounts"
    )
    op.drop_index(
        "ix_email_accounts_org_sync_state", table_name="email_accounts"
    )
    op.drop_table("email_accounts")
    op.execute("DROP TYPE IF EXISTS email_account_sync_state")
    op.execute("DROP TYPE IF EXISTS email_account_provider")
