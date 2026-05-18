"""invitations table — pending sign-up tokens

Backs step 2.5.6 (the invite-user flow). Admins issue a row here; the
recipient redeems with the raw token via the accept-invite page.

Schema choices:
- `token_hash` is a SHA-256 hex of a 32-byte urandom token (NOT bcrypt).
  bcrypt's per-row salt would make WHERE-clause lookup impossible
  without iterating every row. The raw token is already 256 bits of
  entropy — SHA-256 with no salt provides indexed exact-match lookup
  while still being unguessable.
- `expires_at` is set 7 days out by the service layer. Lookup +
  accept both compare against `now()` to reject expired rows.
- `accepted_at` non-null marks the row redeemed; we never delete
  redeemed rows (audit trail).
- TenantScoped → `org_id` FK + RLS policy.

Revision ID: 0036_invitations
Revises: 0035_drop_dr6_cols
Create Date: 2026-05-18 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import CITEXT, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0036_invitations"
down_revision: Union[str, None] = "0035_drop_dr6_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("role_id", UUID(as_uuid=True), nullable=False),
        sa.Column("invited_by", UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_hash", name="uq_invitations_token_hash"
        ),
    )
    op.create_index(
        "ix_invitations_org_id_email",
        "invitations",
        ["org_id", "email"],
    )
    op.create_index(
        "ix_invitations_token_hash",
        "invitations",
        ["token_hash"],
    )

    apply_rls("invitations")


def downgrade() -> None:
    drop_rls("invitations")
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_org_id_email", table_name="invitations")
    op.drop_table("invitations")
