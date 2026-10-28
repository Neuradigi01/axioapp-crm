"""meta_page_tokens — per-(integration, page) Page-token cache.

Meta's lead-ads webhook delivers only `leadgen_id`; the worker has to
call `GET /{leadgen_id}` to fetch the actual field values, and that
call requires a Page-scoped access_token (not the integration's user
token). Re-fetching `/me/accounts` on every webhook delivery would
burn rate limit; instead, `subscribe_page` populates this table once,
and the worker looks up the cached Page token by `page_id`.

Page tokens are stored encrypted (Fernet, via Step 1's `crypto`) for
the same reason user tokens are: a database dump alone leaks no
usable Meta credentials.

The webhook receiver bypasses RLS for the initial `page_id ->
integration` lookup (the request has no JWT, no tenant header — it's
Meta hitting us). After resolving the integration, the worker
pushes the org context onto `RequestContext` so subsequent reads /
writes are RLS-authorised.

Revision ID: 0050_meta_page_tokens
Revises: 0049_webhook_dlq
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0050_meta_page_tokens"
down_revision: Union[str, None] = "0049_webhook_dlq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_page_tokens",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", sa.Text(), nullable=False),
        sa.Column("page_name", sa.Text(), nullable=True),
        # Fernet ciphertext — never plaintext. Use Step 1's
        # `core.integrations.crypto.encrypt` / `decrypt`.
        sa.Column("page_token_enc", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        # CASCADE — disconnecting an integration drops every Page token
        # we had for it. Subscribing again recreates them.
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        # One token per (integration, page) — re-subscribing the same
        # Page replaces (UPSERT) rather than duplicating rows.
        sa.UniqueConstraint(
            "integration_id",
            "page_id",
            name="uq_meta_page_tokens_integration_page",
        ),
    )
    # Webhook receiver looks up by `page_id` ONLY (it doesn't know
    # which integration owns the page until after this lookup). The
    # `page_id` is opaque from Meta's side — it's globally unique
    # across all of Facebook so a single row in this table identifies
    # the destination tenant.
    op.create_index(
        "ix_meta_page_tokens_page", "meta_page_tokens", ["page_id"]
    )
    apply_rls("meta_page_tokens")


def downgrade() -> None:
    drop_rls("meta_page_tokens")
    op.drop_index(
        "ix_meta_page_tokens_page", table_name="meta_page_tokens"
    )
    op.drop_table("meta_page_tokens")
