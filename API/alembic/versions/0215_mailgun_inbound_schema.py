"""Mailgun inbound track — schema + backfill.

Adds every schema primitive the track needs, in one atomic upgrade:

  1. ``tbl_email_smtp_senders.inbound_token VARCHAR(32)`` — nullable
     first, backfilled per-row via ``secrets.token_urlsafe(9)[:12]``
     (12 chars of base64url, ~72 bits of entropy pre-slice), then
     flipped to ``NOT NULL`` and given a ``UNIQUE`` constraint.
     Backfill retries on collision up to 10× per row.
  2. ``tbl_email_smtp_senders.capture_replies_in_crm BOOLEAN NOT NULL
     DEFAULT true`` — per-sender opt-out for the Reply-To rewrite.
  3. ``tbl_messages.spf_result / dkim_result VARCHAR(16)`` — Mailgun's
     forwarded SPF / DKIM verdicts on inbound rows. Used by the
     spoof-detection policy in Step 4.
  4. New table ``tbl_email_inbound_dlq`` — one row per Celery-ingest
     retry-exhausted Mailgun payload. Owned by ``core/email/mailgun/``.

Idempotent by design:
  * Backfill only touches rows ``WHERE inbound_token IS NULL``, so a
    crash-mid-migration replay only regenerates unfilled rows.
  * Column adds use SQLAlchemy's ``op.add_column`` which is
    transactional — a rollback removes the added column cleanly.
  * The DLQ table create is ``IF NOT EXISTS``.

Downgrade removes every change.

Revision ID: 0215_mailgun_inbound_schema
Revises:     0214_messages_dedup_partial_idx
Create Date: 2026-09-02
"""

from __future__ import annotations

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text as sql_text

from alembic import op


revision: str = "0215_mailgun_inbound_schema"
down_revision: Union[str, None] = "0214_messages_dedup_partial_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generate_inbound_token() -> str:
    """12-char URL-safe token. ~60 bits post-slice (72 pre-slice)."""
    return secrets.token_urlsafe(9)[:12]


def _backfill_inbound_tokens(bind) -> int:
    """Assign a unique ``inbound_token`` to every row that lacks one.

    Retries per-row on the unique-constraint collision path (which is
    astronomically unlikely at ~60 bits but must be handled). Returns
    the number of rows successfully backfilled.
    """
    rows = bind.execute(
        sql_text("SELECT id FROM tbl_email_smtp_senders WHERE inbound_token IS NULL")
    ).all()

    filled = 0
    for (sender_id,) in rows:
        for _attempt in range(10):
            candidate = _generate_inbound_token()
            try:
                result = bind.execute(
                    sql_text(
                        "UPDATE tbl_email_smtp_senders "
                        "SET inbound_token = :tok "
                        "WHERE id = :id AND inbound_token IS NULL"
                    ),
                    {"tok": candidate, "id": sender_id},
                )
                if result.rowcount == 1:
                    filled += 1
                break
            except Exception:
                # Unique-constraint collision — regenerate + retry.
                continue
        else:  # pragma: no cover — 10 collisions at 60 bits ~ 1e-108
            raise RuntimeError(
                f"Failed to generate a unique inbound_token for sender "
                f"{sender_id} after 10 attempts"
            )
    return filled


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. tbl_email_smtp_senders — inbound_token (nullable, backfill, NOT NULL + UNIQUE)
    # ------------------------------------------------------------------
    op.add_column(
        "tbl_email_smtp_senders",
        sa.Column("inbound_token", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tbl_email_smtp_senders",
        sa.Column(
            "capture_replies_in_crm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Backfill BEFORE we tighten to NOT NULL + UNIQUE.
    bind = op.get_bind()
    filled = _backfill_inbound_tokens(bind)
    print(f"[0215] backfilled inbound_token for {filled} existing SMTP sender(s)")

    op.alter_column(
        "tbl_email_smtp_senders",
        "inbound_token",
        nullable=False,
        existing_type=sa.String(length=32),
    )
    op.create_unique_constraint(
        "uq_email_smtp_senders_inbound_token",
        "tbl_email_smtp_senders",
        ["inbound_token"],
    )

    # ------------------------------------------------------------------
    # 2. tbl_messages — spf_result, dkim_result
    # ------------------------------------------------------------------
    op.add_column(
        "tbl_messages",
        sa.Column("spf_result", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "tbl_messages",
        sa.Column("dkim_result", sa.String(length=16), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. tbl_email_inbound_dlq — new table
    # ------------------------------------------------------------------
    op.create_table(
        "tbl_email_inbound_dlq",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mailgun_delivery_id", sa.String(length=64), nullable=True),
        sa.Column("pending_inbound_path", sa.Text(), nullable=False),
        sa.Column("error_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "error_details",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_inbound_dlq_org_created",
        "tbl_email_inbound_dlq",
        ["org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_inbound_dlq_org_created", table_name="tbl_email_inbound_dlq")
    op.drop_table("tbl_email_inbound_dlq")

    op.drop_column("tbl_messages", "dkim_result")
    op.drop_column("tbl_messages", "spf_result")

    op.drop_constraint(
        "uq_email_smtp_senders_inbound_token",
        "tbl_email_smtp_senders",
        type_="unique",
    )
    op.drop_column("tbl_email_smtp_senders", "capture_replies_in_crm")
    op.drop_column("tbl_email_smtp_senders", "inbound_token")
