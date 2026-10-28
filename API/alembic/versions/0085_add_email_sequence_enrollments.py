"""email_sequence_enrollments + email_sequence_enrollment_steps —
runtime state for an enrolled contact moving through a sequence.

`email_sequence_enrollments` is one row per (sequence, contact) — a
contact can be enrolled in many sequences but in any one sequence at
most once at a time. The active enrollment is "the row whose `state`
is `active` OR `paused_*`"; on completion the state freezes at
`completed` so re-enrolling becomes legal.

`email_sequence_enrollment_steps` is one row per scheduled step
instance — populated lazily as the scheduler advances through the
sequence (step 1 on enroll, step N on step N-1 success).

The partial index on `(scheduled_at) WHERE sent_at IS NULL AND
skipped = FALSE` is the hot path the beat scheduler reads every 60s.

Tenant-scoped: standard `apply_rls(...)` on `org_id` for both tables.

Revision ID: 0085_email_seq_enrollments
Revises: 0084_add_email_sequences
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0085_email_seq_enrollments"
down_revision: Union[str, None] = "0084_add_email_sequences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENROLLMENT_STATES = (
    "active",
    "completed",
    "paused_on_reply",
    "paused_manual",
    "cancelled",
)


def upgrade() -> None:
    op.create_table(
        "email_sequence_enrollments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        # No FK — post-0037 convention.
        sa.Column("enrolled_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "state_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "current_step_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "state IN ("
            + ", ".join(f"'{s}'" for s in _ENROLLMENT_STATES)
            + ")",
            name="ck_email_sequence_enrollments_state",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["email_sequences.id"]
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Hot path for re-enroll dedupe and per-contact lookups.
    op.create_index(
        "ix_email_sequence_enrollments_seq_contact",
        "email_sequence_enrollments",
        ["sequence_id", "contact_id"],
    )
    # Owner-side filtering (the enrollments-list endpoint).
    op.create_index(
        "ix_email_sequence_enrollments_org_state",
        "email_sequence_enrollments",
        ["org_id", "state"],
    )
    apply_rls("email_sequence_enrollments")

    op.create_table(
        "email_sequence_enrollment_steps",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "skipped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column(
            "message_id", UUID(as_uuid=True), nullable=True
        ),
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
            ["enrollment_id"],
            ["email_sequence_enrollments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"], ["email_sequence_steps.id"]
        ),
        # No ON DELETE on messages — the message row is the audit trail
        # for what was sent; if it ever gets purged the FK silently nulls.
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The beat scheduler reads only due rows — partial index keeps the
    # working set tiny even at 100k+ enrollments.
    op.create_index(
        "ix_email_sequence_enrollment_steps_due",
        "email_sequence_enrollment_steps",
        ["scheduled_at"],
        postgresql_where=sa.text("sent_at IS NULL AND skipped = false"),
    )
    op.create_index(
        "ix_email_sequence_enrollment_steps_enrollment",
        "email_sequence_enrollment_steps",
        ["enrollment_id"],
    )
    apply_rls("email_sequence_enrollment_steps")


def downgrade() -> None:
    drop_rls("email_sequence_enrollment_steps")
    op.drop_index(
        "ix_email_sequence_enrollment_steps_enrollment",
        table_name="email_sequence_enrollment_steps",
    )
    op.drop_index(
        "ix_email_sequence_enrollment_steps_due",
        table_name="email_sequence_enrollment_steps",
    )
    op.drop_table("email_sequence_enrollment_steps")
    drop_rls("email_sequence_enrollments")
    op.drop_index(
        "ix_email_sequence_enrollments_org_state",
        table_name="email_sequence_enrollments",
    )
    op.drop_index(
        "ix_email_sequence_enrollments_seq_contact",
        table_name="email_sequence_enrollments",
    )
    op.drop_table("email_sequence_enrollments")
