"""Add ai_paused + ai_paused_by_user_id + ai_paused_at to tbl_conversations
(``tasks/ai-assistants-omnichannel`` Step 3).

Adds a per-conversation "human took over from AI" boolean flag plus
audit fields for who paused + when. First-come-first-serve semantics
are enforced by the service layer via compare-and-set on ``ai_paused``.

The partial index scopes the dispatch's hot-path query to the majority
case (``ai_paused = false``) so the index stays small even as the
conversations table grows.

Revision ID: 0210_convs_ai_paused
Revises:     0209_ai_bound_channels
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0210_convs_ai_paused"
down_revision: str | None = "0209_ai_bound_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "ai_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column("ai_paused_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "ai_paused_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_ai_paused",
        "tbl_conversations",
        ["org_id", "ai_paused"],
        postgresql_where=sa.text("ai_paused = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_ai_paused", table_name="tbl_conversations")
    op.drop_column("tbl_conversations", "ai_paused_at")
    op.drop_column("tbl_conversations", "ai_paused_by_user_id")
    op.drop_column("tbl_conversations", "ai_paused")
