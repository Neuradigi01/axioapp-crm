"""Let Gmail / Microsoft OAuth mailboxes be the org's default sender.

Before this migration, only ``tbl_email_smtp_senders`` carried
``is_default`` — the resolver in :mod:`shared.email.org_sender` fell
through to the oldest-connected OAuth mailbox silently when no SMTP
default was set. That made "which mailbox will actually send this
automation / conversation reply?" invisible to the operator.

Adds ``is_default`` to ``tbl_email_accounts`` (defaults false) so the
same explicit flag drives OAuth rows too. The
:func:`email_senders.service.set_default_sender` path atomically
clears ``is_default`` on BOTH tables before flipping the winner, so
Postgres never needs to enforce the cross-table uniqueness itself.

Revision ID: 0231_any_sender_default
Revises:     0230_perm_source
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0231_any_sender_default"
down_revision: str | None = "0230_perm_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_email_accounts",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_email_accounts", "is_default")
