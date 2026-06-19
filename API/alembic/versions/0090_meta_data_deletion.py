"""Meta Data Deletion Callback infrastructure (whatsapp-platform-upgrade Step 4).

Creates two new database objects:

1. ``tbl_meta_data_deletion_requests`` — cross-org audit log of every
   signed deletion request Meta sends to our ``/api/v1/integrations/
   meta/data-deletion`` callback. **Intentionally has no ``org_id``
   column** because a single Meta user can connect WhatsApp to multiple
   orgs (separate ES flows); the deletion must affect *all* of them.
   No RLS policy for the same reason — this table is queried by the
   anonymous status page using just the confirmation_code, which is
   itself a high-entropy unguessable token (effectively serves as a
   capability key). Matches the cross-org pattern already used for
   ``tbl_meta_page_tokens`` (which is per-integration, not per-org).

2. ``tbl_integrations.meta_user_id`` — the Meta-side user identifier
   captured during Embedded Signup (Step 2) via ``GET /debug_token``.
   Indexed because the deletion callback's hot path is
   ``WHERE meta_user_id = <X>``. Nullable because legacy manually-
   connected orgs never had this captured; for those rows Meta's
   deletion callback will simply find zero matches and complete
   immediately (correct behavior — the customer pasted a token, not
   a user identity).

Chains after ``0089_wa_app_secret_nullable``.

Revision ID: 0090_meta_data_deletion
Revises: 0089_wa_app_secret_nullable
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0090_meta_data_deletion"
down_revision: Union[str, None] = "0089_wa_app_secret_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("pending", "in_progress", "completed", "failed")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_STATUS_VALUES,
        name="meta_data_deletion_status",
        create_type=True,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tbl_meta_data_deletion_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "confirmation_code",
            sa.String(64),
            nullable=False,
            unique=True,
        ),
        sa.Column("meta_user_id", sa.String(128), nullable=False),
        sa.Column(
            "affected_org_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_STATUS_VALUES,
                name="meta_data_deletion_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_meta_data_deletion_meta_user_id",
        "tbl_meta_data_deletion_requests",
        ["meta_user_id"],
    )
    # NO apply_rls() — this table is intentionally cross-org. The
    # confirmation_code (64-char URL-safe token) is the capability key
    # the public status page reads against.

    op.add_column(
        "tbl_integrations",
        sa.Column("meta_user_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_integrations_meta_user_id",
        "tbl_integrations",
        ["meta_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integrations_meta_user_id",
        table_name="tbl_integrations",
    )
    op.drop_column("tbl_integrations", "meta_user_id")
    op.drop_index(
        "ix_meta_data_deletion_meta_user_id",
        table_name="tbl_meta_data_deletion_requests",
    )
    op.drop_table("tbl_meta_data_deletion_requests")
    op.execute("DROP TYPE IF EXISTS meta_data_deletion_status")
