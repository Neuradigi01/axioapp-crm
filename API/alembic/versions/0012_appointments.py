"""appointments

Creates the `appointments` table (tenant-scoped, RLS-on) plus the
`appointment_status` Postgres ENUM. Indexed for:

- ``ix_appointments_org_scheduled``       — calendar reads per org.
- ``ix_appointments_assigned_scheduled``  — per-user calendar + conflict lookups.
- ``ix_appointments_contact_id``          — "appointments for this contact".

Revision ID: 0012_appointments
Revises: 0011_leads
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0012_appointments"
down_revision: Union[str, None] = "0011_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APPT_STATUS_VALUES = ("scheduled", "completed", "cancelled", "no_show")


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *_APPT_STATUS_VALUES, name="appointment_status", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "appointments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            status_enum,
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=False),
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
            ["assigned_to_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointments_org_id", "appointments", ["org_id"])
    op.create_index(
        "ix_appointments_contact_id", "appointments", ["contact_id"]
    )
    op.create_index(
        "ix_appointments_org_scheduled",
        "appointments",
        ["org_id", "scheduled_at"],
    )
    op.create_index(
        "ix_appointments_assigned_scheduled",
        "appointments",
        ["assigned_to_id", "scheduled_at"],
    )

    apply_rls("appointments")


def downgrade() -> None:
    drop_rls("appointments")
    op.drop_index(
        "ix_appointments_assigned_scheduled", table_name="appointments"
    )
    op.drop_index("ix_appointments_org_scheduled", table_name="appointments")
    op.drop_index("ix_appointments_contact_id", table_name="appointments")
    op.drop_index("ix_appointments_org_id", table_name="appointments")
    op.drop_table("appointments")
    postgresql.ENUM(name="appointment_status").drop(
        op.get_bind(), checkfirst=True
    )
