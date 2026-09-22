"""Add ``archived_at`` to ``tbl_campaigns``.

**Why:** operators need a way to get historical (Sent / Failed) campaigns
out of their default list without hard-deleting them — the shipped
``delete_campaign`` service only accepts ``draft`` / ``failed``, and
even for ``failed`` a hard delete cascades into
``tbl_campaign_messages`` receipts (delivery, open, click history) that
their reporting relies on. Archive is a soft-hide: the row stays with
all its per-message metrics intact, but list/count queries scoped by
default (``include_archived=False``) skip it. The sender-delete
pre-check also skips archived rows, unblocking sender teardown for
orgs whose only remaining reference is a long-since-completed
campaign.

**Column:** ``archived_at TIMESTAMPTZ NULL``. Nullable so a campaign
that has never been archived stays at ``NULL``; ``unarchive`` flips
back to NULL rather than a separate flag. Timestamp doubles as the
"when did the operator hide this?" audit signal so a future admin
UI can render "Archived 12 min ago".

**Index:** partial ``(org_id, archived_at) WHERE archived_at IS NOT NULL``
so the archived-only tab (future feature) is fast without slowing the
common "not archived" list, which uses the existing
``(org_id, created_at DESC)`` index.

Revision ID: 0238_campaigns_archived_at
Revises:     0237_email_inbound_audit
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0238_campaigns_archived_at"
down_revision: str | None = "0237_email_inbound_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_campaigns",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_campaigns_archived_at",
        "tbl_campaigns",
        ["org_id", "archived_at"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_archived_at", table_name="tbl_campaigns")
    op.drop_column("tbl_campaigns", "archived_at")
