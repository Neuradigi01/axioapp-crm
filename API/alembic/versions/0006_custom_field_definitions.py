"""custom_field_definitions

Creates the `custom_field_definitions` table (tenant-scoped, RLS-on)
plus the two Postgres ENUM types (`custom_field_type`,
`custom_field_source`) the model maps to. Unique key is
`(org_id, entity_type, field_key)`; render index covers
`(org_id, entity_type, is_hidden, display_order)` so the `/render`
endpoint is index-only.

Revision ID: 0006_custom_field_definitions
Revises: 0005_audit_logs
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0006_custom_field_definitions"
down_revision: Union[str, None] = "0005_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FIELD_TYPE_VALUES = (
    "text",
    "number",
    "select",
    "multiselect",
    "date",
    "datetime",
    "boolean",
    "phone",
    "email",
    "currency",
)

_FIELD_SOURCE_VALUES = ("system", "pack", "user")


def upgrade() -> None:
    # `create_type=False` keeps `op.create_table` from re-emitting CREATE TYPE
    # for these columns — we issue the explicit creates below so the lifecycle
    # is owned by the migration (matching the column declarations on the model).
    field_type = postgresql.ENUM(
        *_FIELD_TYPE_VALUES,
        name="custom_field_type",
        create_type=False,
    )
    field_source = postgresql.ENUM(
        *_FIELD_SOURCE_VALUES,
        name="custom_field_source",
        create_type=False,
    )
    field_type.create(op.get_bind(), checkfirst=True)
    field_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "custom_field_definitions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("field_label", sa.String(length=128), nullable=False),
        sa.Column("field_type", field_type, nullable=False),
        sa.Column("options", JSONB, nullable=True),
        sa.Column(
            "is_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source",
            field_source,
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column("pack_id", sa.String(length=64), nullable=True),
        sa.Column("validation", JSONB, nullable=True),
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
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "entity_type",
            "field_key",
            name="uq_custom_fields_org_entity_key",
        ),
    )
    op.create_index(
        "ix_custom_field_definitions_org_id",
        "custom_field_definitions",
        ["org_id"],
    )
    op.create_index(
        "ix_custom_field_definitions_entity_type",
        "custom_field_definitions",
        ["entity_type"],
    )
    op.create_index(
        "ix_custom_fields_render",
        "custom_field_definitions",
        ["org_id", "entity_type", "is_hidden", "display_order"],
    )

    apply_rls("custom_field_definitions")


def downgrade() -> None:
    drop_rls("custom_field_definitions")
    op.drop_index(
        "ix_custom_fields_render", table_name="custom_field_definitions"
    )
    op.drop_index(
        "ix_custom_field_definitions_entity_type",
        table_name="custom_field_definitions",
    )
    op.drop_index(
        "ix_custom_field_definitions_org_id",
        table_name="custom_field_definitions",
    )
    op.drop_table("custom_field_definitions")

    postgresql.ENUM(name="custom_field_source").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="custom_field_type").drop(op.get_bind(), checkfirst=True)
