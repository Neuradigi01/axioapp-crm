"""Custom events — org-defined named events staff can fire against a
contact to trigger workflows + templates.

Two tables:

  * ``tbl_custom_events`` — one row per event definition (visa_expired,
    membership_ended, ...). Owner/Admin create these; staff fire them.
    Unique ``(org_id, event_key)`` where ``event_key`` is the stable
    identifier that publishes on the bus as ``custom.<event_key>``.
  * ``tbl_custom_event_occurrences`` — log of each fire. Contact-id
    optional (an org may fire events without a specific contact, e.g.
    system-level). ``fired_by_user_id`` is null when a workflow (not a
    human) publishes the event.

Both tables carry ``org_id`` + RLS. Both integrate with the shared
``TenantScoped`` mixin so ORM SELECTs are auto-filtered.

Revision ID: 0226_custom_events
Revises:     0225_rename_embed_to_api_keys
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0226_custom_events"
down_revision: str | None = "0225_rename_embed_to_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tbl_custom_events --------------------------------------------------
    op.create_table(
        "tbl_custom_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
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
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial unique index: an org can't have two live definitions
    # sharing the same event_key. A soft-deleted row is allowed to
    # coexist with a fresh live row of the same key so operators can
    # recreate a deleted event without a hard-purge step.
    op.create_index(
        "ux_custom_events_org_key_live",
        "tbl_custom_events",
        ["org_id", "event_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_custom_events_org_created",
        "tbl_custom_events",
        ["org_id", sa.text("created_at DESC")],
    )
    op.create_check_constraint(
        "ck_custom_events_key_format",
        "tbl_custom_events",
        r"event_key ~ '^[a-z][a-z0-9_]{0,63}$'",
    )

    # --- tbl_custom_event_occurrences ---------------------------------------
    op.create_table(
        "tbl_custom_event_occurrences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_custom_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "fired_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fired_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_custom_event_occ_event_fired",
        "tbl_custom_event_occurrences",
        ["event_id", sa.text("fired_at DESC")],
    )
    op.create_index(
        "ix_custom_event_occ_contact_fired",
        "tbl_custom_event_occurrences",
        ["contact_id", sa.text("fired_at DESC")],
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )
    op.create_index(
        "ix_custom_event_occ_org_fired",
        "tbl_custom_event_occurrences",
        ["org_id", sa.text("fired_at DESC")],
    )

    # --- RLS policies ---------------------------------------------------------
    for table in ("tbl_custom_events", "tbl_custom_event_occurrences"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
            """
        )


def downgrade() -> None:
    for table in ("tbl_custom_event_occurrences", "tbl_custom_events"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_index("ix_custom_event_occ_org_fired", table_name="tbl_custom_event_occurrences")
    op.drop_index("ix_custom_event_occ_contact_fired", table_name="tbl_custom_event_occurrences")
    op.drop_index("ix_custom_event_occ_event_fired", table_name="tbl_custom_event_occurrences")
    op.drop_table("tbl_custom_event_occurrences")
    op.drop_constraint(
        "ck_custom_events_key_format", "tbl_custom_events", type_="check"
    )
    op.drop_index("ix_custom_events_org_created", table_name="tbl_custom_events")
    op.drop_index("ux_custom_events_org_key_live", table_name="tbl_custom_events")
    op.drop_table("tbl_custom_events")
