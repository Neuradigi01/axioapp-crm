"""Chatbot precedence flag + trigger-diagnostics table
(``tasks/chatbot-builder`` Step 5).

Two additions:

  * ``tbl_organizations.chatbot_disable_inline_when_active_bot`` —
    boolean flag (default TRUE) that gates the precedence rule
    (README Decision §12). When TRUE and a live bot matches an
    inbound message, the inline auto-reply / keyword-rules paths
    inside ``conversations.service.receive_webhook`` skip that
    message. Operators can flip to FALSE per-org from the settings
    page in a later step to opt back into the "both fire" behaviour.

  * ``tbl_chatbot_trigger_diagnostics`` — one row per matcher
    decision the operator would want to inspect ("why did / didn't
    my bot fire"). Fed by the Step-5 matcher and read by a future
    diagnostics UI. Nightly sweeper (Step 6) TTLs rows older than
    90 days.

Chains after ``0191_bf_chatbots_perm``. Reversible.

Revision ID: 0192_chatbot_precedence
Revises:     0191_bf_chatbots_perm
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0192_chatbot_precedence"
down_revision: str | None = "0191_bf_chatbots_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Org-level precedence flag ----------------------------------------
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "chatbot_disable_inline_when_active_bot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # --- Trigger-diagnostics table ----------------------------------------
    op.create_table(
        "tbl_chatbot_trigger_diagnostics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        # e.g. 'skipped_by_priority', 'opted_out', 'active_run_exists',
        # 'no_match', 'regex_error'. String not enum — the reasons
        # grow over time and enum churn is worse than the readability
        # loss on a JOIN.
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chatbot_trigger_diag_org_created",
        "tbl_chatbot_trigger_diagnostics",
        ["org_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_chatbot_trigger_diag_conv",
        "tbl_chatbot_trigger_diagnostics",
        ["conversation_id"],
    )

    op.execute(
        "ALTER TABLE tbl_chatbot_trigger_diagnostics ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tbl_chatbot_trigger_diagnostics_tenant_isolation
            ON tbl_chatbot_trigger_diagnostics
            USING (org_id::text = current_setting('app.current_org_id', true))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tbl_chatbot_trigger_diagnostics_tenant_isolation "
        "ON tbl_chatbot_trigger_diagnostics"
    )
    op.drop_index(
        "ix_chatbot_trigger_diag_conv",
        table_name="tbl_chatbot_trigger_diagnostics",
    )
    op.drop_index(
        "ix_chatbot_trigger_diag_org_created",
        table_name="tbl_chatbot_trigger_diagnostics",
    )
    op.drop_table("tbl_chatbot_trigger_diagnostics")

    op.drop_column("tbl_organizations", "chatbot_disable_inline_when_active_bot")
