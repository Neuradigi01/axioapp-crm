"""Add ``bot_muted_until`` to ``tbl_conversations`` so the End Bot
node can temporarily silence the trigger matcher on a conversation
after a flow completes.

Nullable timestamp. When NULL the matcher fires as normal; when set
to a future UTC timestamp the matcher records ``bot_muted`` and skips
firing until that time passes. Set by the ``end_bot`` node handler
whenever its ``mute_hours`` config is > 0.

Chains after ``0195_bf_chatbot_seeds``.

Revision ID: 0196_conv_bot_muted_until
Revises:     0195_bf_chatbot_seeds
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0196_conv_bot_muted_until"
down_revision: str | None = "0195_bf_chatbot_seeds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "bot_muted_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_conversations", "bot_muted_until")
