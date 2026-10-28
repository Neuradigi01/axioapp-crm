"""tbl_whatsapp_account_configs — AI settings columns
(whatsapp-platform-upgrade Step 19).

Wires the orphan ``tbl_conversations.ai_handling`` flag to a real
dispatch pipeline. Four new columns on the existing config row:

  * ``ai_handling_default_enabled BOOL DEFAULT FALSE`` — when on,
    every new WhatsApp conversation lands with ``ai_handling=true``
    and the AI agent answers first. Power-user toggle; off by
    default (opt-in per conversation is the safer default).

  * ``ai_confidence_threshold FLOAT DEFAULT 0.6`` — AI response
    below this confidence escalates to a human (handover).

  * ``ai_handover_keywords TEXT[]`` — phrases that trigger immediate
    handover regardless of confidence ("talk to person", "इंसान से
    बात", etc.). Default list seeded by the migration.

  * ``ai_system_prompt TEXT NULL`` — optional org-specific persona /
    business context prepended to every AI call. The default empty
    state falls back to a built-in baseline.

Chains after ``0106_assignment_rules``.

Revision ID: 0107_wa_ai_settings
Revises: 0106_assignment_rules
Create Date: 2026-06-23 00:07:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0107_wa_ai_settings"
down_revision: Union[str, None] = "0106_assignment_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_HANDOVER_KEYWORDS = (
    "talk to person",
    "talk to a human",
    "talk to agent",
    "agent please",
    "human please",
    "real person",
    "इंसान से बात",
    "इंसान से बात करनी है",
    "मानव से बात",
)


def upgrade() -> None:
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "ai_handling_default_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "ai_confidence_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.6"),
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "ai_handover_keywords",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text(
                "ARRAY["
                + ", ".join(f"'{k}'" for k in _DEFAULT_HANDOVER_KEYWORDS)
                + "]::text[]"
            ),
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "ai_system_prompt",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_whatsapp_account_configs", "ai_system_prompt")
    op.drop_column("tbl_whatsapp_account_configs", "ai_handover_keywords")
    op.drop_column("tbl_whatsapp_account_configs", "ai_confidence_threshold")
    op.drop_column(
        "tbl_whatsapp_account_configs", "ai_handling_default_enabled"
    )
