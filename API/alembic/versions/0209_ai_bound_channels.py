"""Add bound_channels JSONB + GIN index to tbl_ai_assistants
(``tasks/ai-assistants-omnichannel`` Step 1).

Adds ``bound_channels JSONB NOT NULL DEFAULT '[]'::jsonb`` so each
assistant declares which channels (``ai_widget`` / ``whatsapp`` /
``email``) it should auto-answer on. Plus a GIN index for the
dispatch's hot-path query ``WHERE bound_channels ? :channel``.

Existing rows get ``[]`` via ``server_default`` — operators opt in
per channel; nothing gets auto-bound.

Revision ID: 0209_ai_bound_channels
Revises:     0208_janitor_and_gdpr_log
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0209_ai_bound_channels"
down_revision: str | None = "0208_janitor_and_gdpr_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_ai_assistants",
        sa.Column(
            "bound_channels",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_ai_assistants_bound_channels_gin",
        "tbl_ai_assistants",
        ["bound_channels"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_assistants_bound_channels_gin",
        table_name="tbl_ai_assistants",
    )
    op.drop_column("tbl_ai_assistants", "bound_channels")
