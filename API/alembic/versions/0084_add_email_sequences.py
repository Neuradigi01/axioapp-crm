"""email_sequences + email_sequence_steps — sequence definitions.

A sequence is the static definition: name + ordered list of (delay_days,
template_id) steps. Per-contact runtime state lives in migration 0085's
enrollment tables.

`email_sequence_steps.template_id` is a plain FK with no ON DELETE — Step
6's templates are soft-deleted (`deleted_at`), so the FK survives a
template "delete". Hard delete is intentionally not surfaced by the API.

Tenant-scoped: standard `apply_rls(...)` on `org_id` for both tables.

Revision ID: 0084_add_email_sequences
Revises: 0083_add_email_templates
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0084_add_email_sequences"
down_revision: Union[str, None] = "0083_add_email_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_sequences",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
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
    op.create_index(
        "ix_email_sequences_org_active",
        "email_sequences",
        ["org_id", "is_active"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Live-only name uniqueness inside an org. Soft-deleted rows are
    # excluded so a future "create with same name" can succeed.
    op.create_index(
        "uq_email_sequences_org_name",
        "email_sequences",
        ["org_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    apply_rls("email_sequences")

    op.create_table(
        "email_sequence_steps",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column(
            "delay_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("template_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["email_sequences.id"], ondelete="CASCADE"
        ),
        # No ON DELETE on templates — soft-deleted templates must not
        # vanish from sequence definitions.
        sa.ForeignKeyConstraint(
            ["template_id"], ["email_templates.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sequence_id",
            "step_order",
            name="uq_email_sequence_steps_seq_order",
        ),
    )
    op.create_index(
        "ix_email_sequence_steps_seq",
        "email_sequence_steps",
        ["sequence_id", "step_order"],
    )
    apply_rls("email_sequence_steps")


def downgrade() -> None:
    drop_rls("email_sequence_steps")
    op.drop_index(
        "ix_email_sequence_steps_seq", table_name="email_sequence_steps"
    )
    op.drop_table("email_sequence_steps")
    drop_rls("email_sequences")
    op.drop_index(
        "uq_email_sequences_org_name", table_name="email_sequences"
    )
    op.drop_index(
        "ix_email_sequences_org_active", table_name="email_sequences"
    )
    op.drop_table("email_sequences")
