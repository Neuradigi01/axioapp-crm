"""email_templates — org-scoped library of reusable email templates.

One row per template. Body stored as both HTML + plain text — the
plain text is auto-derived from HTML on save (stdlib HTMLParser
extractor in `service.py`) when the caller doesn't provide it.

`variables_used` is JSONB array of dot-path strings (e.g.
`["contact.first_name", "lead.pipeline_stage"]`) extracted at save
time from the subject + body. Step 10's editor uses this to render
the right side-bar without re-parsing.

`created_by` is a plain UUID (no FK) per the post-0037 convention.
`deleted_at` is the soft-delete tombstone — Step 7's sequences
reference templates and must survive a template delete.

Tenant-scoped: standard `apply_rls("email_templates")` policy on
`org_id`. RLS authorises every read/write.

Revision ID: 0083_add_email_templates
Revises: 0082_email_accounts
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0083_add_email_templates"
down_revision: Union[str, None] = "0082_email_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        # Auto-derived on save when not supplied.
        sa.Column("body_text", sa.Text(), nullable=False),
        # Dot-paths used in subject + body_html; stored sorted.
        sa.Column(
            "variables_used",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # No FK — post-0037 convention.
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Hot-path list query: live templates for the org.
    op.create_index(
        "ix_email_templates_org_active",
        "email_templates",
        ["org_id", "is_active"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Name uniqueness within the org for live templates only —
    # soft-deleted rows are excluded so a future "create with same
    # name" doesn't conflict with a tombstone.
    op.create_index(
        "uq_email_templates_org_name",
        "email_templates",
        ["org_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    apply_rls("email_templates")


def downgrade() -> None:
    drop_rls("email_templates")
    op.drop_index(
        "uq_email_templates_org_name", table_name="email_templates"
    )
    op.drop_index(
        "ix_email_templates_org_active", table_name="email_templates"
    )
    op.drop_table("email_templates")
