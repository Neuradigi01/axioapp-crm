"""email_message_opens + email_message_clicks + contacts.email_opt_out.

Three changes in one migration:

  1. `email_message_opens` — one row per pixel fire. No dedupe; rapid
     re-fires (a contact opens the email multiple times) all count.
     `ip_hash` + `user_agent_hash` are sha256 prefixes so we don't
     store raw PII.

  2. `email_message_clicks` — one row per redirector hit. `target_url`
     is the original href (post-decode) — the redirector strips it
     from the URL fragment so we keep an audit of what was clicked.

  3. `contacts.email_opt_out` (BOOL, default false) +
     `contacts.email_opt_out_at` (timestamptz). When set, Step 5's
     `send_email` raises `OptedOut(451)` instead of dispatching, and
     Step 7's sequence scheduler cancels active enrollments for the
     contact on the next tick. Required by CAN-SPAM (US) + DPDP (IN).

Tenant-scoped: standard `apply_rls(...)` on `org_id` for both new
tables. Contacts already has the policy from a prior migration.

Revision ID: 0086_add_email_tracking
Revises: 0085_email_seq_enrollments
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0086_add_email_tracking"
down_revision: Union[str, None] = "0085_email_seq_enrollments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- opens ----------------------------------------------------------
    op.create_table(
        "email_message_opens",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # sha256(ip)[:16] — never store raw IP per DPDP minimisation.
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("user_agent_hash", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        # No ON DELETE on messages — purging a message row should
        # cascade-delete its opens, so SET NULL would be wrong here.
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_message_opens_message_opened",
        "email_message_opens",
        ["message_id", "opened_at"],
    )
    apply_rls("email_message_opens")

    # --- clicks ---------------------------------------------------------
    op.create_table(
        "email_message_clicks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column(
            "clicked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_message_clicks_message_clicked",
        "email_message_clicks",
        ["message_id", "clicked_at"],
    )
    apply_rls("email_message_clicks")

    # --- contacts opt-out ------------------------------------------------
    # IF NOT EXISTS so re-running the migration on a partially-migrated
    # DB doesn't error.
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS email_opt_out BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS email_opt_out_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS email_opt_out_at")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS email_opt_out")
    drop_rls("email_message_clicks")
    op.drop_index(
        "ix_email_message_clicks_message_clicked",
        table_name="email_message_clicks",
    )
    op.drop_table("email_message_clicks")
    drop_rls("email_message_opens")
    op.drop_index(
        "ix_email_message_opens_message_opened",
        table_name="email_message_opens",
    )
    op.drop_table("email_message_opens")
