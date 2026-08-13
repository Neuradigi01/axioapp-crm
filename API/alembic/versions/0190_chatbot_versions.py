"""Chatbot version-history table
(``tasks/chatbot-builder`` Step 2).

Every save on ``tbl_chatbots`` appends a row here with the prior
``graph`` + ``trigger_config`` JSONB blobs so operators can compare +
roll back. Uniquely keyed on ``(chatbot_id, version_number)`` so
concurrent saves cannot collide on the same version slot.

Standalone from Step 1's ``0189_chatbots_init`` so the version-history
migration can be rolled back independently if the UI never lands
(Steps 13-15).

Chains after ``0189_chatbots_init``. RLS policy matches the pattern
used by every tenant-scoped table in this build.

Revision ID: 0190_chatbot_versions
Revises:     0189_chatbots_init
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0190_chatbot_versions"
down_revision: str | None = "0189_chatbots_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_chatbot_versions",
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
            "chatbot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "graph",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "chatbot_id",
            "version_number",
            name="uq_chatbot_versions_bot_version",
        ),
    )
    op.create_index(
        "ix_chatbot_versions_bot_created",
        "tbl_chatbot_versions",
        ["chatbot_id", sa.text("created_at DESC")],
    )

    op.execute("ALTER TABLE tbl_chatbot_versions ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tbl_chatbot_versions_tenant_isolation ON tbl_chatbot_versions
            USING (org_id::text = current_setting('app.current_org_id', true))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tbl_chatbot_versions_tenant_isolation "
        "ON tbl_chatbot_versions"
    )
    op.drop_index(
        "ix_chatbot_versions_bot_created",
        table_name="tbl_chatbot_versions",
    )
    op.drop_table("tbl_chatbot_versions")
