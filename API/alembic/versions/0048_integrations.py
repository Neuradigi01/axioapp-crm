"""integrations — per-org OAuth-token storage for Google Ads + Meta Ads.

One row per `(org_id, provider)`. Tokens are stored as Fernet ciphertext
(`access_token_enc`, `refresh_token_enc`) — never plaintext. The
encryption key lives in the API container's environment
(`INTEGRATIONS_ENCRYPTION_KEY`), so a database dump alone leaks no
usable OAuth credentials.

Two Postgres enums:
  - `integration_provider`: which ad platform (`google_ads` | `meta_ads`).
  - `integration_status`: lifecycle (`connected` | `disconnected` |
    `expired` | `error`).

`connected_by` / `disconnected_by` are plain UUIDs with no FK to
`users(id)` per the post-0037 convention — the legacy `users` table is
on soak and FKs to it are forbidden in new work.

Tenant isolation: standard `apply_rls("integrations")` policy on
`org_id`. The provider-specific code (Steps 2 + 4 in this track) opens
sessions inside an existing tenant context — RLS authorises every
read/write.

Revision ID: 0048_integrations
Revises: 0047_embed_submissions
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0048_integrations"
down_revision: Union[str, None] = "0047_embed_submissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `create_type=False` because we own the enum lifecycle via the DO
# blocks below — same idempotency pattern as 0047_embed_submissions
# (a stray enum from an aborted earlier run would otherwise blow
# up `op.create_table`'s implicit CREATE TYPE).
_PROVIDER_ENUM = PgEnum(
    "google_ads",
    "meta_ads",
    name="integration_provider",
    create_type=False,
)
_STATUS_ENUM = PgEnum(
    "connected",
    "disconnected",
    "expired",
    "error",
    name="integration_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE integration_provider AS ENUM (
                'google_ads',
                'meta_ads'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE integration_status AS ENUM (
                'connected',
                'disconnected',
                'expired',
                'error'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "integrations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", _PROVIDER_ENUM, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("account_label", sa.Text(), nullable=True),
        # Fernet ciphertext. NULL when disconnected — the row stays so
        # the connect/disconnect history survives across reconnections.
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        # Granted OAuth scopes — Postgres TEXT[]. Lets the UI surface
        # "Connected with X scopes" and lets us detect when a scope set
        # the user previously granted has been narrowed (re-prompt).
        sa.Column(
            "scopes",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            _STATUS_ENUM,
            nullable=False,
            server_default=sa.text("'disconnected'"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), nullable=True
        ),
        # No FK on connected_by / disconnected_by — post-0037 convention.
        sa.Column("connected_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "disconnected_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("disconnected_by", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # One row per (org, provider) for v1. Multi-account-per-provider
        # is a future surface — when added, this constraint becomes
        # (org_id, provider, account_id) and the existing rows backfill.
        sa.UniqueConstraint(
            "org_id", "provider", name="uq_integrations_org_provider"
        ),
    )

    # Lookup index for `GET /integrations` list endpoint (rare — Owners
    # land on the Settings page occasionally) and for the OAuth callback
    # which does a single SELECT by org. (UNIQUE constraint already
    # gives us the index; explicit index here for the org-only filter.)
    op.create_index(
        "ix_integrations_org",
        "integrations",
        ["org_id"],
    )

    apply_rls("integrations")


def downgrade() -> None:
    drop_rls("integrations")
    op.drop_index("ix_integrations_org", table_name="integrations")
    op.drop_table("integrations")
    op.execute("DROP TYPE IF EXISTS integration_status")
    op.execute("DROP TYPE IF EXISTS integration_provider")
