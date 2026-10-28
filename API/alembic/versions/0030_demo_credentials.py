"""demo_credentials

A dev/staging-only lookup table that pairs a seeded demo user with
its plaintext password. The login page's "Test logins" dropdown
fetches from `/api/v1/_dev/demo-logins`, which JOINs `users` with
this table.

The table itself migrates everywhere (one alembic ledger). The data-
hiding is at the application layer: seed scripts only insert rows for
users they create with `is_demo=True`, and the dev router that
exposes the JOIN is mounted only when `IS_DEVELOPMENT=true`. Production
neither writes rows here nor exposes the endpoint.

No `org_id` column — this table is intentionally global; the row IS
the secret. `user_id` FKs back to `users` which carries org_id, and
the dev endpoint always returns the user's org slug alongside.

Revision ID: 0030_demo_credentials
Revises: 0029_users_is_demo
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0030_demo_credentials"
down_revision: Union[str, None] = "0029_users_is_demo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demo_credentials",
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("plain_password", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("demo_credentials")
