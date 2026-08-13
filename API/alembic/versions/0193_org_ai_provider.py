"""AI provider configured flag on org
(``tasks/chatbot-builder`` Step 10).

Boolean gate that the ``single_ai_message`` + ``assign_ai_assistant``
node handlers check before firing. Default FALSE — orgs opt in
after a future AI-provider track wires up OpenAI / Anthropic /
Gemini credentials. Until then, bot flows carrying AI nodes take
the ``error`` port with a helpful ``ai_not_configured`` reason.

Chains after ``0192_chatbot_precedence``.

Revision ID: 0193_org_ai_provider
Revises:     0192_chatbot_precedence
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0193_org_ai_provider"
down_revision: str | None = "0192_chatbot_precedence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "ai_provider_configured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_organizations", "ai_provider_configured")
