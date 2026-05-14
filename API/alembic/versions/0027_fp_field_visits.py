"""fp_field_visits — site visits + visit photos

Two tenant-scoped, RLS-on tables for the furniture pack's field-ops
module + one ENUM:

  - `fp_field_visit_purpose` enum: measurement | installation | inspection
  - `fp_field_visits`        — one row per scheduled site visit
  - `fp_field_visit_photos`  — site visit photos

Scheduling reuses the core appointments engine (FK → appointments).

Note: 0025 is `fp_inventory_cover_url` and 0026 is `fp_custom_orders`.
The step file mentions `0025_fp_field_visits.py` because the plan was
written before those hops existed; the actual revision is the next in
sequence.

Revision ID: 0027_fp_field_visits
Revises: 0026_fp_custom_orders
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0027_fp_field_visits"
down_revision: Union[str, None] = "0026_fp_custom_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PURPOSES = ("measurement", "installation", "inspection")


def upgrade() -> None:
    purpose_enum = postgresql.ENUM(
        *_PURPOSES, name="fp_field_visit_purpose", create_type=False
    )
    bind = op.get_bind()
    purpose_enum.create(bind, checkfirst=True)

    # --- fp_field_visits ---
    op.create_table(
        "fp_field_visits",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", purpose_enum, nullable=False),
        sa.Column("custom_order_id", UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_url", sa.String(length=512), nullable=True),
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
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["custom_order_id"],
            ["fp_custom_orders.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "appointment_id", name="uq_fp_field_visits_appointment"
        ),
    )
    op.create_index(
        "ix_fp_field_visits_appointment",
        "fp_field_visits",
        ["appointment_id"],
    )
    op.create_index(
        "ix_fp_field_visits_custom_order",
        "fp_field_visits",
        ["custom_order_id"],
    )
    op.create_index(
        "ix_fp_field_visits_org_completed",
        "fp_field_visits",
        ["org_id", "completed_at"],
    )

    # --- fp_field_visit_photos ---
    op.create_table(
        "fp_field_visit_photos",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.String(length=255), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
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
            ["visit_id"], ["fp_field_visits.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fp_field_visit_photos_visit",
        "fp_field_visit_photos",
        ["visit_id"],
    )

    apply_rls("fp_field_visits")
    apply_rls("fp_field_visit_photos")


def downgrade() -> None:
    drop_rls("fp_field_visit_photos")
    drop_rls("fp_field_visits")
    op.drop_index(
        "ix_fp_field_visit_photos_visit",
        table_name="fp_field_visit_photos",
    )
    op.drop_table("fp_field_visit_photos")
    op.drop_index(
        "ix_fp_field_visits_org_completed",
        table_name="fp_field_visits",
    )
    op.drop_index(
        "ix_fp_field_visits_custom_order",
        table_name="fp_field_visits",
    )
    op.drop_index(
        "ix_fp_field_visits_appointment",
        table_name="fp_field_visits",
    )
    op.drop_table("fp_field_visits")
    bind = op.get_bind()
    postgresql.ENUM(name="fp_field_visit_purpose").drop(bind, checkfirst=True)
