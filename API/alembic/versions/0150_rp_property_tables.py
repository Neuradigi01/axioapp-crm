"""rp_property_tables — real-estate pack Property + PropertyImage

Two tenant-scoped, RLS-on tables for the Real Estate pack's Property
module + supporting indexes:

  * ``tbl_rp_properties`` — one row per property listing (title,
    type, category, price, address block, physical details, status
    state machine, custom_data).
  * ``tbl_rp_property_images`` — gallery images bound to a property
    via ``FK ON DELETE CASCADE``. Partial unique index enforces at
    most one ``is_featured=true`` image per property.

Indexes:

  * ``ix_rp_properties_org_status_created`` — hot filter path for
    the owner-dashboard tabs (org + status, ordered by created_at).
  * ``ix_rp_properties_org_city_type`` — filter combo (city + type).
  * ``uq_rp_properties_org_slug`` — internal admin analytics slug is
    unique per org. Public URLs use a Fernet token (Step 5), not
    the slug.
  * ``ix_rp_properties_amenities_gin`` — GIN on JSONB for
    array-contains tag search (added in a follow-up step; the DDL
    is here as a comment for reference).
  * ``ix_rp_property_images_property_order`` — gallery ordered read.
  * ``uq_rp_property_images_featured`` — partial UNIQUE
    ``(property_id) WHERE is_featured``.

RLS uses the shared ``apply_rls`` helper (policy ``org_isolation``,
column ``org_id``), matching every other tenant-scoped table.

Revision ID: 0150_rp_property_tables
Revises: 0149_call_recording_file
Create Date: 2026-07-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0150_rp_property_tables"
down_revision: Union[str, None] = "0149_call_recording_file"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- tbl_rp_properties -----------------------------------------
    op.create_table(
        "tbl_rp_properties",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("property_type", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default=sa.text("'INR'"),
        ),
        sa.Column("address_line", sa.String(length=500), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("pincode", sa.String(length=20), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Integer(), nullable=True),
        sa.Column("area_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("area_unit", sa.String(length=20), nullable=True),
        sa.Column(
            "amenities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("contact_person", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "custom_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.CheckConstraint(
            "length(title) >= 3",
            name="ck_rp_properties_title_min_len",
        ),
        sa.UniqueConstraint("org_id", "slug", name="uq_rp_properties_org_slug"),
    )
    op.create_index(
        "ix_rp_properties_org_id",
        "tbl_rp_properties",
        ["org_id"],
    )
    op.create_index(
        "ix_rp_properties_org_status_created",
        "tbl_rp_properties",
        ["org_id", "status", "created_at"],
    )
    op.create_index(
        "ix_rp_properties_org_city_type",
        "tbl_rp_properties",
        ["org_id", "city", "property_type"],
    )
    # GIN index on the amenities JSONB for future tag-contains
    # searches — cheap to build now while the table is empty.
    op.execute(
        "CREATE INDEX ix_rp_properties_amenities_gin "
        "ON tbl_rp_properties USING gin (amenities)"
    )

    # ----- tbl_rp_property_images ------------------------------------
    op.create_table(
        "tbl_rp_property_images",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_rp_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("image_path", sa.String(length=500), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=50), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_rp_property_images_org_id",
        "tbl_rp_property_images",
        ["org_id"],
    )
    op.create_index(
        "ix_rp_property_images_property_id",
        "tbl_rp_property_images",
        ["property_id"],
    )
    op.create_index(
        "ix_rp_property_images_property_order",
        "tbl_rp_property_images",
        ["property_id", "display_order"],
    )
    # Partial unique index: at most one featured image per property.
    op.execute(
        "CREATE UNIQUE INDEX uq_rp_property_images_featured "
        "ON tbl_rp_property_images (property_id) "
        "WHERE is_featured = true"
    )

    apply_rls("tbl_rp_properties")
    apply_rls("tbl_rp_property_images")


def downgrade() -> None:
    drop_rls("tbl_rp_property_images")
    drop_rls("tbl_rp_properties")
    op.execute("DROP INDEX IF EXISTS uq_rp_property_images_featured")
    op.drop_index(
        "ix_rp_property_images_property_order",
        table_name="tbl_rp_property_images",
    )
    op.drop_index(
        "ix_rp_property_images_property_id",
        table_name="tbl_rp_property_images",
    )
    op.drop_index(
        "ix_rp_property_images_org_id",
        table_name="tbl_rp_property_images",
    )
    op.drop_table("tbl_rp_property_images")
    op.execute("DROP INDEX IF EXISTS ix_rp_properties_amenities_gin")
    op.drop_index(
        "ix_rp_properties_org_city_type",
        table_name="tbl_rp_properties",
    )
    op.drop_index(
        "ix_rp_properties_org_status_created",
        table_name="tbl_rp_properties",
    )
    op.drop_index("ix_rp_properties_org_id", table_name="tbl_rp_properties")
    op.drop_table("tbl_rp_properties")
