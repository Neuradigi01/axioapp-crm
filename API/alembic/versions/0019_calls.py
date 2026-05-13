"""calls + call_transcripts + call_outcomes

Three tenant-scoped, RLS-on tables plus the `call_direction` ENUM.
Indexes:
  - calls(org_id, started_at)   for the list view
  - calls(contact_id)            for "calls for this contact"
  - calls(outcome_id)            for analytics group-bys
  - call_outcomes UNIQUE(org_id, key)
  - call_transcripts(call_id)

Revision ID: 0019_calls
Revises: 0018_conversations
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0019_calls"
down_revision: Union[str, None] = "0018_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DIRECTION_VALUES = ("in", "out")


def upgrade() -> None:
    direction_enum = postgresql.ENUM(
        *_DIRECTION_VALUES, name="call_direction", create_type=False
    )
    direction_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "call_outcomes",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column(
            "color",
            sa.String(length=32),
            server_default=sa.text("'#6b7280'"),
            nullable=False,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="uq_call_outcomes_org_key"),
    )

    op.create_table(
        "calls",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "duration_sec",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("outcome_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.String(length=512), nullable=True),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "custom_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["outcome_id"], ["call_outcomes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calls_org_started_at", "calls", ["org_id", "started_at"])
    op.create_index("ix_calls_contact_id", "calls", ["contact_id"])
    op.create_index("ix_calls_outcome_id", "calls", ["outcome_id"])

    op.create_table(
        "call_transcripts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_call_transcripts_call_id", "call_transcripts", ["call_id"]
    )

    apply_rls("call_outcomes")
    apply_rls("calls")
    apply_rls("call_transcripts")


def downgrade() -> None:
    drop_rls("call_transcripts")
    drop_rls("calls")
    drop_rls("call_outcomes")
    op.drop_index("ix_call_transcripts_call_id", table_name="call_transcripts")
    op.drop_table("call_transcripts")
    op.drop_index("ix_calls_outcome_id", table_name="calls")
    op.drop_index("ix_calls_contact_id", table_name="calls")
    op.drop_index("ix_calls_org_started_at", table_name="calls")
    op.drop_table("calls")
    op.drop_table("call_outcomes")
    postgresql.ENUM(name="call_direction").drop(
        op.get_bind(), checkfirst=True
    )
