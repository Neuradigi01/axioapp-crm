"""tbl_conversation_tags + tbl_conversation_tag_assignments
(whatsapp-platform-upgrade Step 14).

Two RLS-scoped tables:

  1. ``tbl_conversation_tags`` — operator-defined labels (e.g.
     ``high-value`` red, ``urgent`` rose). Unique per-org on lower-case
     name so the picker can't surface visual duplicates. The
     ``created_by_user_id`` is informational; tags don't have an
     owner (any org member with `conversations.write` can assign
     existing tags, but the `settings.conversations.manage` permission
     is required to create / edit / delete).

  2. ``tbl_conversation_tag_assignments`` — many-to-many bridge.
     ``ON DELETE CASCADE`` on both tag_id + conversation_id so a tag
     delete fans out cleanly and removing a conversation doesn't leave
     orphan assignments. Unique on ``(conversation_id, tag_id)`` to
     keep the join idempotent.

RLS uses the same `app.org_id` policy as every other tenant-scoped
table.

Chains after ``0099_conv_internal_notes``.

Revision ID: 0100_conv_tags
Revises: 0099_conv_internal_notes
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0100_conv_tags"
down_revision: Union[str, None] = "0099_conv_internal_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- tbl_conversation_tags -----------------------------------
    op.create_table(
        "tbl_conversation_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        # Fixed palette key — frontend maps to a Tailwind class set
        # (e.g. `red` → bg-rose-100 text-rose-700 ring-rose-200).
        # Keep it short (≤16) so the column scans cheaply.
        sa.Column(
            "color",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'zinc'"),
        ),
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
    )
    # Case-insensitive uniqueness: 'High-Value' and 'high-value' should
    # collide. Postgres functional index.
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_tags_org_lower_name "
        "ON tbl_conversation_tags (org_id, lower(name))"
    )
    op.execute(
        "ALTER TABLE tbl_conversation_tags ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_conversation_tags
        ON tbl_conversation_tags
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )

    # ----- tbl_conversation_tag_assignments -----------------------
    op.create_table(
        "tbl_conversation_tag_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_conversation_tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tagged_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "tagged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "tag_id",
            name="uq_conv_tag_assignment",
        ),
    )
    op.create_index(
        "ix_conv_tag_assignments_conversation",
        "tbl_conversation_tag_assignments",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conv_tag_assignments_tag",
        "tbl_conversation_tag_assignments",
        ["tag_id"],
    )
    op.execute(
        "ALTER TABLE tbl_conversation_tag_assignments "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_conversation_tag_assignments
        ON tbl_conversation_tag_assignments
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_conversation_tag_assignments "
        "ON tbl_conversation_tag_assignments"
    )
    op.drop_index(
        "ix_conv_tag_assignments_tag",
        table_name="tbl_conversation_tag_assignments",
    )
    op.drop_index(
        "ix_conv_tag_assignments_conversation",
        table_name="tbl_conversation_tag_assignments",
    )
    op.drop_table("tbl_conversation_tag_assignments")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_conversation_tags "
        "ON tbl_conversation_tags"
    )
    op.execute("DROP INDEX IF EXISTS uq_conv_tags_org_lower_name")
    op.drop_table("tbl_conversation_tags")
