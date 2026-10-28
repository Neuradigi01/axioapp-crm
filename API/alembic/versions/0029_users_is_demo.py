"""users.is_demo

Adds a `is_demo` boolean column on `users` so we can flag the seeded
test accounts. Production rows default to `false`. Read by the
dev-only `/api/v1/_dev/demo-logins` endpoint that backs the login
page's "Test logins" dropdown.

Revision ID: 0029_users_is_demo
Revises: 0028_billing
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0029_users_is_demo"
down_revision: Union[str, None] = "0028_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_demo")
