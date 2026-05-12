"""activities

Creates the `activities` table (tenant-scoped, RLS-on) plus the
`activity_type` Postgres ENUM and the composite timeline-read index
`(org_id, entity_type, entity_id, created_at DESC)` that the
`GET /activities` endpoint relies on.

Revision ID: 0008_activities
Revises: 0007_contacts
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0008_activities"
down_revision: Union[str, None] = "0007_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTIVITY_TYPE_VALUES = (
    "note",
    "call",
    "email",
    "whatsapp",
    "status_change",
    "task",
)


def upgrade() -> None:
    activity_type = postgresql.ENUM(
        *_ACTIVITY_TYPE_VALUES,
        name="activity_type",
        create_type=False,
    )
    activity_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "activities",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", activity_type, nullable=False),
        sa.Column(
            "payload",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activities_org_id", "activities", ["org_id"])
    op.create_index("ix_activities_user_id", "activities", ["user_id"])

    # Composite timeline-read index: lookups always filter
    # (org_id, entity_type, entity_id) and order by created_at desc.
    op.execute(
        "CREATE INDEX ix_activities_timeline "
        "ON activities (org_id, entity_type, entity_id, created_at DESC)"
    )

    apply_rls("activities")


def downgrade() -> None:
    drop_rls("activities")
    op.execute("DROP INDEX IF EXISTS ix_activities_timeline")
    op.drop_index("ix_activities_user_id", table_name="activities")
    op.drop_index("ix_activities_org_id", table_name="activities")
    op.drop_table("activities")
    postgresql.ENUM(name="activity_type").drop(op.get_bind(), checkfirst=True)
