"""tbl_email_smtp_senders — per-org SMTP sender identities.

Ships the ``core/email_senders`` module's storage:

  * ``tbl_email_smtp_senders`` — one row per (org, from_address)
    manual-SMTP sender. Fernet-encrypted password column, 6-digit
    verification code (sha256 hash + 30-minute expiry), default flag,
    TLS-mode column.

The unique (org_id, from_address) constraint stops accidental
duplicate submissions of the same sender. RLS + the ORM tenant
listener carry the tenant filter — no additional per-tenant index
beyond the (org_id, from_address) UNIQUE + the standalone org_id
index on the ForeignKey.

Revision ID: 0169_email_smtp_senders
Revises:     0168_phone_dedup_index
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0169_email_smtp_senders"
down_revision: str | None = "0168_phone_dedup_index"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_email_smtp_senders",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_address", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("smtp_host", sa.String(length=253), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("smtp_username", sa.String(length=255), nullable=False),
        sa.Column("smtp_password_enc", sa.Text(), nullable=False),
        sa.Column(
            "tls_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'starttls'"),
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "verification_code_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "verification_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.UniqueConstraint(
            "org_id",
            "from_address",
            name="uq_email_smtp_senders_org_from",
        ),
    )
    op.create_index(
        "ix_email_smtp_senders_org",
        "tbl_email_smtp_senders",
        ["org_id"],
    )

    # `updated_at` bumping trigger — SQLAlchemy `onupdate=now()`
    # covers ORM writes, but a raw UPDATE (backfills, admin scripts)
    # would leave the column stale otherwise. Cheap belt-and-braces.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tbl_email_smtp_senders_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_email_smtp_senders_set_updated_at
        BEFORE UPDATE ON tbl_email_smtp_senders
        FOR EACH ROW EXECUTE FUNCTION
            tbl_email_smtp_senders_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_email_smtp_senders_set_updated_at "
        "ON tbl_email_smtp_senders;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS tbl_email_smtp_senders_set_updated_at();"
    )
    op.drop_index(
        "ix_email_smtp_senders_org",
        table_name="tbl_email_smtp_senders",
    )
    op.drop_table("tbl_email_smtp_senders")
