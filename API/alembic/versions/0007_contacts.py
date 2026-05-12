"""contacts

Creates the `contacts` table (tenant-scoped, RLS-on) plus the indexes
the list-and-search endpoint relies on:

- Per-tenant phone + email lookup indexes.
- GIN trigram on `full_name` for the fuzzy `q=` search (requires
  ``pg_trgm``; the extension is created `IF NOT EXISTS`).
- GIN on the `tags` array column for `tag=` filters.
- GIN on `custom_data` for the `custom.<key>=value` filter style.

Revision ID: 0007_contacts
Revises: 0006_custom_field_definitions
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0007_contacts"
down_revision: Union[str, None] = "0006_custom_field_definitions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "contacts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.String(length=64)),
            server_default=sa.text("ARRAY[]::varchar[]"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_contacts_org_id", "contacts", ["org_id"])
    op.create_index("ix_contacts_org_phone", "contacts", ["org_id", "phone"])
    op.create_index("ix_contacts_org_email", "contacts", ["org_id", "email"])
    op.create_index("ix_contacts_org_source", "contacts", ["org_id", "source"])

    # Trigram GIN index on full_name → fuzzy + ILIKE search performance.
    op.execute(
        "CREATE INDEX ix_contacts_full_name_trgm "
        "ON contacts USING gin (full_name gin_trgm_ops)"
    )
    # GIN on tags array → `tags && ARRAY[..]` and `tags @> ARRAY[..]` fast.
    op.execute(
        "CREATE INDEX ix_contacts_tags_gin ON contacts USING gin (tags)"
    )
    # GIN on custom_data → fast key/value containment for `custom.<k>=v`.
    op.execute(
        "CREATE INDEX ix_contacts_custom_data_gin "
        "ON contacts USING gin (custom_data jsonb_path_ops)"
    )

    apply_rls("contacts")


def downgrade() -> None:
    drop_rls("contacts")
    op.execute("DROP INDEX IF EXISTS ix_contacts_custom_data_gin")
    op.execute("DROP INDEX IF EXISTS ix_contacts_tags_gin")
    op.execute("DROP INDEX IF EXISTS ix_contacts_full_name_trgm")
    op.drop_index("ix_contacts_org_source", table_name="contacts")
    op.drop_index("ix_contacts_org_email", table_name="contacts")
    op.drop_index("ix_contacts_org_phone", table_name="contacts")
    op.drop_index("ix_contacts_org_id", table_name="contacts")
    op.drop_table("contacts")
    # pg_trgm extension is shared with future migrations; leave it in
    # place so a downgrade doesn't surprise other modules.
