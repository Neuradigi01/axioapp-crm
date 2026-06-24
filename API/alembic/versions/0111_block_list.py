"""WhatsApp block list table
(whatsapp-platform-upgrade Step 23).

Org-scoped block list for inbound + outbound. The inbound webhook
silently drops messages from blocked numbers (no conversation row,
no auto-reply); the outbound adapter + campaign send-guard refuse
to ship to a blocked number with a friendly 4xx-shaped error.

Unique on ``(org_id, phone_number)`` so the same number can be
blocked once per tenant — and a different org can independently
block / allow it. RLS via the standard ``app.org_id`` policy.

Chains after ``0110_bf_opt_in_perm``.

Revision ID: 0111_block_list
Revises: 0110_bf_opt_in_perm
Create Date: 2026-06-24 04:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0111_block_list"
down_revision: Union[str, None] = "0110_bf_opt_in_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REASON_VALUES = ("spam", "fraud", "requested", "harassment", "other")


def upgrade() -> None:
    reason_enum = postgresql.ENUM(
        *_REASON_VALUES, name="whatsapp_block_reason"
    )
    reason_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tbl_whatsapp_block_list",
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
        # Normalised E.164 (digits only, no leading +). Same shape as
        # `tbl_contacts.phone` so the inbound webhook can compare with
        # zero ceremony. We keep the column flexible (VARCHAR(32))
        # rather than enforcing E.164 at the DB layer — different orgs
        # have wildly different upstream phone formats and the block
        # service normalises on the way in.
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(
                *_REASON_VALUES,
                name="whatsapp_block_reason",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'other'"),
        ),
        sa.Column(
            "blocked_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "org_id", "phone_number", name="uq_block_list_org_phone"
        ),
    )

    # Fast-path lookup on the inbound webhook + outbound send.
    op.create_index(
        "ix_block_list_org_phone",
        "tbl_whatsapp_block_list",
        ["org_id", "phone_number"],
    )

    # RLS — tenant isolation via app.org_id setting.
    op.execute("ALTER TABLE tbl_whatsapp_block_list ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tbl_whatsapp_block_list FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_block_list
            ON tbl_whatsapp_block_list
            USING (org_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_block_list ON tbl_whatsapp_block_list"
    )
    op.drop_index(
        "ix_block_list_org_phone", table_name="tbl_whatsapp_block_list"
    )
    op.drop_table("tbl_whatsapp_block_list")
    sa.Enum(name="whatsapp_block_reason").drop(op.get_bind(), checkfirst=True)
