"""Extend ``tbl_ai_assistants`` with lead-capture columns
(``tasks/ai-assistants`` Step 16).

Adds three columns:

  * ``lead_capture_mode`` — ENUM('off','detect_email','ask_at_turn').
    ``off`` default: existing assistants keep their current behaviour.
    ``detect_email`` regex-scans every user message + upserts a lead
    when an email lands. ``ask_at_turn`` asks the visitor for their
    email at turn N (via a system-side prompt injection) + captures
    when they provide it.
  * ``lead_capture_turn_n`` — INT default 3. Which conversation turn
    triggers the ask when ``mode='ask_at_turn'``.
  * ``lead_capture_message`` — TEXT nullable. The exact ask text the
    runtime injects; when NULL the runtime uses a sensible default.

All nullable / defaulted so existing rows survive the ALTER without
a data backfill.

Revision ID: 0206_ai_lead_capture
Revises:     0205_extend_embed_keys_ai
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0206_ai_lead_capture"
down_revision: str | None = "0205_extend_embed_keys_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    lead_capture_mode = sa.Enum(
        "off",
        "detect_email",
        "ask_at_turn",
        name="ai_assistant_lead_capture_mode",
        create_type=True,
    )
    lead_capture_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tbl_ai_assistants",
        sa.Column(
            "lead_capture_mode",
            sa.Enum(
                "off",
                "detect_email",
                "ask_at_turn",
                name="ai_assistant_lead_capture_mode",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'off'"),
        ),
    )
    op.add_column(
        "tbl_ai_assistants",
        sa.Column(
            "lead_capture_turn_n",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
    )
    op.add_column(
        "tbl_ai_assistants",
        sa.Column(
            "lead_capture_message",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_ai_assistants", "lead_capture_message")
    op.drop_column("tbl_ai_assistants", "lead_capture_turn_n")
    op.drop_column("tbl_ai_assistants", "lead_capture_mode")
    sa.Enum(
        name="ai_assistant_lead_capture_mode",
    ).drop(op.get_bind(), checkfirst=True)
