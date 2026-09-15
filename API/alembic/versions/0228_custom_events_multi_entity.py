"""Multi-entity custom events — an event can bind to a date field on
Contact / Lead / Appointment (not just Contact).

Schema changes:

  * ``tbl_custom_events.entity_type`` — ``'contact' | 'lead' |
    'appointment'``. Default ``'contact'`` (existing manual-only rows
    stay contact-scoped, matches their historical behaviour).
  * ``tbl_custom_event_occurrences.entity_type`` + ``entity_id`` — a
    per-fire pointer to the row that owned the date match. For
    contact-scoped events ``entity_id == contact_id`` (both set for
    backward compat). For lead/appointment events, ``entity_id`` is
    the lead/appointment PK and ``contact_id`` is the related
    contact hydrated from that row so workflows still get
    ``{{ contact.email }}`` variables.

Dedup index gains ``entity_type`` so a lead's ``visa_renewal_date``
and a contact's ``visa_expiry_date`` — both tied to the same
``event_key`` conceptually — can't collide. (In practice they'd be
separate event definitions, but the index invariant should hold.)

Revision ID: 0228_multi_entity_events
Revises:     0227_custom_events_schedule
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0228_multi_entity_events"
down_revision: str | None = "0227_custom_events_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- tbl_custom_events ---------------------------------------------------
    op.add_column(
        "tbl_custom_events",
        sa.Column(
            "entity_type",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'contact'"),
        ),
    )
    op.create_check_constraint(
        "ck_custom_events_entity_type",
        "tbl_custom_events",
        "entity_type IN ('contact', 'lead', 'appointment')",
    )

    # --- tbl_custom_event_occurrences ---------------------------------------
    op.add_column(
        "tbl_custom_event_occurrences",
        sa.Column(
            "entity_type",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'contact'"),
        ),
    )
    op.add_column(
        "tbl_custom_event_occurrences",
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_custom_event_occ_entity_type",
        "tbl_custom_event_occurrences",
        "entity_type IN ('contact', 'lead', 'appointment')",
    )
    # Backfill entity_id from contact_id for existing rows (all
    # existing rows are contact-scoped by the pre-migration default).
    op.execute(
        "UPDATE tbl_custom_event_occurrences SET entity_id = contact_id "
        "WHERE entity_id IS NULL AND contact_id IS NOT NULL"
    )

    # Rebuild the dedup index to include entity_type — prevents a
    # theoretical collision if one org has a contact-scoped and a
    # lead-scoped event share dedup grain.
    op.drop_index(
        "ux_custom_event_occ_dedup", table_name="tbl_custom_event_occurrences"
    )
    op.create_index(
        "ux_custom_event_occ_dedup",
        "tbl_custom_event_occurrences",
        ["event_id", "entity_type", "entity_id", "period_key"],
        unique=True,
        postgresql_where=sa.text("entity_id IS NOT NULL"),
    )
    # Fast lookup for a contact's timeline (still by contact_id — the
    # timeline API is Contact-page-centric even when the event fired
    # against a Lead attached to that contact).
    # existing index ix_custom_event_occ_contact_fired already covers this.


def downgrade() -> None:
    op.drop_index(
        "ux_custom_event_occ_dedup", table_name="tbl_custom_event_occurrences"
    )
    op.create_index(
        "ux_custom_event_occ_dedup",
        "tbl_custom_event_occurrences",
        ["event_id", "contact_id", "period_key"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )
    op.drop_constraint(
        "ck_custom_event_occ_entity_type",
        "tbl_custom_event_occurrences",
        type_="check",
    )
    op.drop_column("tbl_custom_event_occurrences", "entity_id")
    op.drop_column("tbl_custom_event_occurrences", "entity_type")

    op.drop_constraint(
        "ck_custom_events_entity_type", "tbl_custom_events", type_="check"
    )
    op.drop_column("tbl_custom_events", "entity_type")
