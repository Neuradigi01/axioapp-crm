"""Lead routing infrastructure — round-robin counter + per-org config.

Two additions for Step-6's centralised ingestion:

  1. `org_settings.lead_routing_config` (JSONB, default
     `{"strategy": "round_robin"}`) — the editable config the
     Settings UI will surface (Step 8). v1 only honours `strategy:
     round_robin`; the JSONB shape leaves room for future strategies
     (sticky_by_source, by_geo, by_store) without a schema change.

  2. `lead_routing_state` — per-org cursor for the round-robin
     algorithm. Single row per org keyed on `org_id`. The
     `next_assignee_index` integer is atomically incremented via
     `UPDATE ... RETURNING` so two concurrent ingests never pick
     the same assignee.

`leads.assigned_to_id` column is INTENTIONALLY NOT added here — it
already exists on the `leads` table from the initial Phase-2.11
schema. The spec was written before that landed.

The `leads.own` permission key is registered at app startup via the
module descriptor in `core/leads/module.py` (the lifespan hook in
`main.py` walks every module's `permissions` list and UPSERTs them
into the `permissions` table). No migration row needed.

Revision ID: 0051_routing_and_dedup
Revises: 0050_meta_page_tokens
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0051_routing_and_dedup"
down_revision: Union[str, None] = "0050_meta_page_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. lead_routing_config on org_settings. Default
    # `{"strategy":"round_robin"}` so orgs that never visit the
    # Settings page still get sane routing behaviour.
    op.add_column(
        "org_settings",
        sa.Column(
            "lead_routing_config",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"strategy\":\"round_robin\"}'::jsonb"
            ),
        ),
    )

    # 2. lead_routing_state — per-org round-robin counter. Standalone
    # table (not on org_settings) because the counter changes on every
    # ingest while the settings row is read-mostly; isolating them
    # keeps Settings-page caches simple.
    #
    # Single-row-per-org enforced by `org_id` PRIMARY KEY (NOT NULL by
    # definition). Caller upserts via `ON CONFLICT (org_id) DO UPDATE
    # SET next_assignee_index = ... RETURNING ...` — atomic and
    # contention-safe up to ~thousands of writes/sec which is well
    # beyond v1 scale.
    #
    # No RLS — this is an internal counter, never queried by user-
    # facing endpoints. The ingest service runs after tenant context
    # is set anyway, but it queries by `WHERE org_id = :id`, not via
    # a wildcard scan, so RLS isn't load-bearing.
    op.create_table(
        "lead_routing_state",
        sa.Column(
            "org_id", UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "next_assignee_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("org_id"),
    )


def downgrade() -> None:
    op.drop_table("lead_routing_state")
    op.drop_column("org_settings", "lead_routing_config")
