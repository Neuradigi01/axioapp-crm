"""import_presets — per-org and system mapping presets for bulk import.

A preset is a `{csv_column: crm_field_key | null}` dict the frontend
applies as the default mapping when a user uploads an export from a
known source platform. Two layers:

  - **System presets** (`is_system=true`, `org_id IS NULL`) — shipped
    by the seed migration `0043_seed_system_import_presets`, one per
    known platform (zoho / hubspot / salesforce / freshsales /
    generic_csv). Read-only to every org; never mutated by the app.
  - **Org-owned presets** (`is_system=false`, `org_id=<org>`) — created
    by Owners/Admins via `POST /leads/import/presets` to save a
    bespoke "our Excel template v3" mapping for repeated use.

RLS is custom (not the default `apply_rls` helper) because system
rows must be visible across orgs while org-owned rows stay isolated:

  SELECT: `is_system OR org_id = current_setting('app.org_id')`
  WRITE : `NOT is_system AND org_id = current_setting('app.org_id')`

A SQLAlchemy `TenantScoped` mixin can't model this — its auto-filter
forces `org_id = <ctx>` and rejects NULL. The model declares `org_id`
nullable directly; service-layer queries combine the OR predicate
explicitly so the read path works regardless of RLS posture.

`created_by` is a plain UUID with no FK to `users(id)` per the
post-0037 convention (the legacy `users` table is on soak).

Revision ID: 0042_import_presets
Revises: 0041_lead_imports
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0042_import_presets"
down_revision: Union[str, None] = "0041_lead_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_presets",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # NULL = system preset (visible to every org).
        sa.Column("org_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_platform", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mapping", JSONB, nullable=False),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        # No FK to users — post-0037 convention.
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
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
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Uniqueness on (org, platform, name) including system rows.
    # Postgres treats NULL as distinct in unique constraints, so we
    # coalesce to a sentinel UUID for system rows (`org_id IS NULL`).
    op.execute(
        """
        CREATE UNIQUE INDEX import_presets_org_platform_name_uq
        ON import_presets (
            COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid),
            source_platform,
            name
        )
        """
    )
    op.create_index(
        "ix_import_presets_lookup",
        "import_presets",
        ["source_platform", "org_id"],
    )

    # Custom RLS — system rows visible to every org, org-owned rows
    # isolated. Writes only on org-owned rows in the active org.
    op.execute("ALTER TABLE import_presets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY import_presets_read ON import_presets FOR SELECT
        USING (
            is_system
            OR org_id = current_setting('app.org_id', true)::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY import_presets_write ON import_presets FOR ALL
        USING (
            NOT is_system
            AND org_id = current_setting('app.org_id', true)::uuid
        )
        WITH CHECK (
            NOT is_system
            AND org_id = current_setting('app.org_id', true)::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS import_presets_write ON import_presets")
    op.execute("DROP POLICY IF EXISTS import_presets_read ON import_presets")
    op.execute("ALTER TABLE import_presets DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_import_presets_lookup", table_name="import_presets")
    op.execute("DROP INDEX IF EXISTS import_presets_org_platform_name_uq")
    op.drop_table("import_presets")
