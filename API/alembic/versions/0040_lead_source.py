"""lead.source — provenance column on the leads table.

Adds the `lead_source` Postgres ENUM (manual | bulk_import | widget |
google_ads | meta_ads) and the matching NOT NULL `source` column on
`leads`. Existing rows backfill to `'manual'` via `server_default` at
ADD-COLUMN time — semantically correct since every pre-existing lead
was created by a user typing into the modal. The server_default is
then dropped so future inserts must state intent (the Pydantic schema
default covers HTTP callers; later ingestion-channel tracks will
override explicitly).

The future bulk-import, embeddable-widget, and ad-integration tracks
all write to this column with their own enum values. No other schema
change is needed to support them.

Revision ID: 0040_lead_source
Revises: 0039_standard_field_overrides
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0040_lead_source"
down_revision: Union[str, None] = "0039_standard_field_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEAD_SOURCE_VALUES = ("manual", "bulk_import", "widget", "google_ads", "meta_ads")


def upgrade() -> None:
    source_enum = postgresql.ENUM(
        *_LEAD_SOURCE_VALUES, name="lead_source", create_type=False
    )
    source_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "leads",
        sa.Column(
            "source",
            source_enum,
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    # Drop the server-side default now that existing rows are backfilled.
    # Future inserts state intent via the Pydantic default in LeadCreate
    # or via the per-channel ingestion service in later tracks.
    op.alter_column("leads", "source", server_default=None)


def downgrade() -> None:
    op.drop_column("leads", "source")
    postgresql.ENUM(name="lead_source").drop(op.get_bind(), checkfirst=True)
