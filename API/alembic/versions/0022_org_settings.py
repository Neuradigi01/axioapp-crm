"""org_settings

One tenant-scoped, RLS-on table for organisation preferences. Single
row per org enforced by UNIQUE(org_id). Defaults baked in via
server_default so a brand-new org gets sensible Indian-CRM values
(INR / 18% GST / Asia/Kolkata / en-IN) without a separate seed.

Revision ID: 0022_org_settings
Revises: 0021_campaigns
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0022_org_settings"
down_revision: Union[str, None] = "0021_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_settings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),

        # Store profile
        sa.Column("store_name", sa.String(length=255), nullable=True),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column("gst_number", sa.String(length=32), nullable=True),
        sa.Column("address_line1", sa.String(length=255), nullable=True),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=128), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),

        # Locale + fiscal
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'INR'"),
            nullable=False,
        ),
        sa.Column(
            "tax_rate",
            sa.Numeric(5, 2),
            server_default=sa.text("18.00"),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Kolkata'"),
            nullable=False,
        ),
        sa.Column(
            "locale",
            sa.String(length=16),
            server_default=sa.text("'en-IN'"),
            nullable=False,
        ),

        # AI
        sa.Column(
            "ai_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("ai_personality", sa.Text(), nullable=True),
        sa.Column("ai_welcome_message", sa.Text(), nullable=True),

        # Reviews automation
        sa.Column(
            "reviews_auto_request_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "reviews_auto_request_delay_hours",
            sa.Integer(),
            server_default=sa.text("24"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_org_settings_org_id"),
    )

    apply_rls("org_settings")


def downgrade() -> None:
    drop_rls("org_settings")
    op.drop_table("org_settings")
