"""leads

Creates the `leads` table (tenant-scoped, RLS-on) plus the `lead_status`
Postgres ENUM and the read-hot indexes:

- ``ix_leads_org_stage``       — `(org_id, pipeline_stage)` for kanban column reads.
- ``ix_leads_assigned_to_id``  — "my leads" lookups.
- ``ix_leads_contact_id``      — joins back to contacts.

Revision ID: 0011_leads
Revises: 0010_pipelines
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0011_leads"
down_revision: Union[str, None] = "0010_pipelines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEAD_STATUS_VALUES = ("active", "won", "lost")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_LEAD_STATUS_VALUES, name="lead_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "leads",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_stage", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column("budget", sa.Numeric(14, 2), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column(
            "custom_data",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_org_id", "leads", ["org_id"])
    op.create_index("ix_leads_contact_id", "leads", ["contact_id"])
    op.create_index("ix_leads_assigned_to_id", "leads", ["assigned_to_id"])
    op.create_index(
        "ix_leads_org_stage", "leads", ["org_id", "pipeline_stage"]
    )

    apply_rls("leads")


def downgrade() -> None:
    drop_rls("leads")
    op.drop_index("ix_leads_org_stage", table_name="leads")
    op.drop_index("ix_leads_assigned_to_id", table_name="leads")
    op.drop_index("ix_leads_contact_id", table_name="leads")
    op.drop_index("ix_leads_org_id", table_name="leads")
    op.drop_table("leads")
    postgresql.ENUM(name="lead_status").drop(op.get_bind(), checkfirst=True)
