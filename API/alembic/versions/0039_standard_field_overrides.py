"""standard_field_overrides — per-org overrides for canonical form fields.

Parallel surface to `custom_field_definitions`. Where custom fields lets
an org *add* columns to an entity, this table stores the org's
overrides for the *standard* columns (label, required, hidden, min/max,
display order). NULL in any override column means "inherit registry
default" — the Step 3 render endpoint coalesces.

Tenant-scoped (RLS-on). Unique key `(org_id, entity, field_key)` plus
the covering `(org_id, entity)` index for the per-entity GET in the
service.

`created_by` / `updated_by` carry plain UUID — no FK to `users` per the
post-0037 convention (the legacy `users` table is on soak; UUID columns
join semantically against `tbl_user_login.legacy_uuid` at the app
layer).

Revision ID: 0039_standard_field_overrides
Revises: 0038_organizations_created_via
Create Date: 2026-05-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0039_standard_field_overrides"
down_revision: Union[str, None] = "0038_organizations_created_via"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "standard_field_overrides",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("field_key", sa.String(length=128), nullable=False),

        # Presentational overrides — NULL means "inherit registry default".
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("placeholder", sa.String(length=255), nullable=True),
        sa.Column("help_text", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), nullable=True),
        sa.Column("min_value", sa.Numeric(20, 6), nullable=True),
        sa.Column("max_value", sa.Numeric(20, 6), nullable=True),
        sa.Column("step_value", sa.Numeric(20, 6), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),

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
        # No FK — see module docstring (post-0037 convention).
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=True),

        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "entity",
            "field_key",
            name="uq_standard_field_overrides_org_entity_field",
        ),
    )
    op.create_index(
        "ix_sfo_org_entity",
        "standard_field_overrides",
        ["org_id", "entity"],
    )

    apply_rls("standard_field_overrides")


def downgrade() -> None:
    drop_rls("standard_field_overrides")
    op.drop_index("ix_sfo_org_entity", table_name="standard_field_overrides")
    op.drop_table("standard_field_overrides")
