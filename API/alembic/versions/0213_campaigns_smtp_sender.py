"""Add smtp_sender_id column to tbl_campaigns so Email campaigns can
dispatch via a verified SMTP sender (tbl_email_smtp_senders) instead
of only via an OAuth mailbox (tbl_email_accounts).

Chains after 0212_bf_conv_assign_perm.

Column shape:
  * ``smtp_sender_id UUID NULL`` with FK to ``tbl_email_smtp_senders(id)``
    ``ON DELETE RESTRICT`` — same posture as ``email_account_id``. A
    delete of a sender identity should be refused while an Email
    campaign still points at it; the operator is expected to change
    the sender OR delete the campaign first.
  * Nullable by design — WhatsApp/SMS campaigns don't populate either
    sender column, and Email campaigns populate exactly one.
  * Indexed for future join reporting (which campaigns used which
    sender identity).

CHECK constraint ``ck_campaigns_email_exactly_one_sender``:
  For Email-channel rows, exactly one of ``email_account_id`` or
  ``smtp_sender_id`` must be set. Non-Email rows have both NULL.
  This is a belt-and-braces guard on top of the Pydantic validator
  in ``schemas.py`` — a caller that bypasses the API (raw SQL, some
  future migration) still can't create an ambiguous / no-sender
  Email campaign row.

Downgrade drops the CHECK, index, FK, then the column.

Revision ID: 0213_campaigns_smtp_sender
Revises:     0212_bf_conv_assign_perm
Create Date: 2026-09-01
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0213_campaigns_smtp_sender"
down_revision: Union[str, None] = "0212_bf_conv_assign_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_campaigns",
        sa.Column("smtp_sender_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_campaigns_smtp_sender",
        source_table="tbl_campaigns",
        referent_table="tbl_email_smtp_senders",
        local_cols=["smtp_sender_id"],
        remote_cols=["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_campaigns_smtp_sender_id",
        "tbl_campaigns",
        ["smtp_sender_id"],
    )
    op.create_check_constraint(
        "ck_campaigns_email_exactly_one_sender",
        "tbl_campaigns",
        # For Email channel: exactly one of the two sender columns is
        # set. For non-Email channels: both must be NULL. Postgres
        # treats NULL != NULL, so we cast to text for the XOR.
        "(channel <> 'email' AND email_account_id IS NULL AND smtp_sender_id IS NULL) "
        "OR (channel = 'email' AND "
        "    ((email_account_id IS NOT NULL AND smtp_sender_id IS NULL) OR "
        "     (email_account_id IS NULL AND smtp_sender_id IS NOT NULL)))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_campaigns_email_exactly_one_sender",
        "tbl_campaigns",
        type_="check",
    )
    op.drop_index("ix_campaigns_smtp_sender_id", table_name="tbl_campaigns")
    op.drop_constraint("fk_campaigns_smtp_sender", "tbl_campaigns", type_="foreignkey")
    op.drop_column("tbl_campaigns", "smtp_sender_id")
