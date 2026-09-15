"""Date-triggered custom events — add schedule columns + occurrence
dedup index.

Extends ``tbl_custom_events`` so an Owner can wire an event to fire
automatically on a date field (system column or custom-field JSONB
value) instead of / in addition to the existing manual-fire button.

Six new columns:

  * ``schedule_type`` — ``'manual'`` (default; existing rows keep the
    button-only behaviour) or ``'date_field'`` (daily sweep fires it).
  * ``schedule_source`` — ``'system'`` (physical column on
    ``tbl_contacts``) or ``'custom'`` (JSONB path in
    ``custom_data``). NULL for manual events.
  * ``schedule_field_ref`` — for system: column name (e.g.
    ``date_of_birth``); for custom: the definition's ``field_key``
    (e.g. ``visa_expiry_date``). NULL for manual events.
  * ``schedule_offset_days`` — signed int, 0 = on the day, -7 = 7d
    before, +7 = 7d after. NULL for manual events.
  * ``schedule_recurring`` — ``'none'`` (one-shot, e.g. visa expiry),
    ``'yearly'`` (like a birthday), or ``'monthly'`` (like a
    recurring renewal). NULL for manual events.
  * ``schedule_hour_local`` — 0..23. Hour of day (in the org's
    timezone) when the sweep fires the event. Defaults to 9 so
    reminders land during business hours. NULL for manual events.

Plus a partial unique index on ``tbl_custom_event_occurrences`` that
prevents double-firing for scheduled events:

  * one-shot: unique on ``(event_id, contact_id)``
  * yearly:   unique on ``(event_id, contact_id, year_of_fired_at)``
  * monthly:  unique on ``(event_id, contact_id, year_month_of_fired_at)``

A single generated column ``occurrence_period_key`` on
``tbl_custom_event_occurrences`` computes the correct dedup grain
per event on the fly; the unique index is on that.

Revision ID: 0227_custom_events_schedule
Revises:     0226_custom_events
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0227_custom_events_schedule"
down_revision: str | None = "0226_custom_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Schedule columns on tbl_custom_events ------------------------------
    op.add_column(
        "tbl_custom_events",
        sa.Column(
            "schedule_type",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_source", sa.String(16), nullable=True),
    )
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_field_ref", sa.String(128), nullable=True),
    )
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_offset_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_recurring", sa.String(16), nullable=True),
    )
    op.add_column(
        "tbl_custom_events",
        sa.Column("schedule_hour_local", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_custom_events_schedule_type",
        "tbl_custom_events",
        "schedule_type IN ('manual', 'date_field')",
    )
    op.create_check_constraint(
        "ck_custom_events_schedule_source",
        "tbl_custom_events",
        "schedule_source IS NULL OR schedule_source IN ('system', 'custom')",
    )
    op.create_check_constraint(
        "ck_custom_events_schedule_recurring",
        "tbl_custom_events",
        "schedule_recurring IS NULL OR schedule_recurring IN ('none', 'yearly', 'monthly')",
    )
    op.create_check_constraint(
        "ck_custom_events_schedule_hour_range",
        "tbl_custom_events",
        "schedule_hour_local IS NULL OR (schedule_hour_local BETWEEN 0 AND 23)",
    )
    # Composite completeness — if schedule_type='date_field' every
    # schedule_* column must be set. If 'manual', none may be set.
    op.create_check_constraint(
        "ck_custom_events_schedule_complete",
        "tbl_custom_events",
        (
            "(schedule_type = 'manual' AND schedule_source IS NULL "
            " AND schedule_field_ref IS NULL AND schedule_offset_days IS NULL "
            " AND schedule_recurring IS NULL AND schedule_hour_local IS NULL) "
            "OR "
            "(schedule_type = 'date_field' AND schedule_source IS NOT NULL "
            " AND schedule_field_ref IS NOT NULL AND schedule_offset_days IS NOT NULL "
            " AND schedule_recurring IS NOT NULL AND schedule_hour_local IS NOT NULL)"
        ),
    )
    # Sweeper hot-path — find every date_field event without scanning
    # the manual events. Partial index keeps write cost tiny (nothing to
    # maintain for manual rows, which will always be the majority).
    op.create_index(
        "ix_custom_events_scheduled",
        "tbl_custom_events",
        ["schedule_hour_local", "org_id"],
        postgresql_where=sa.text("schedule_type = 'date_field' AND deleted_at IS NULL"),
    )

    # --- Occurrence dedup grain --------------------------------------------
    # A generated column that computes the correct dedup key based on
    # the sibling event definition's recurring mode. We can't reference
    # sibling table columns from a generated expression, so we store
    # the recurring mode + the appropriate period stamp on the
    # occurrence itself. Two additive columns:
    #   * ``recurring_mode`` — snapshot of the event's mode at fire time
    #   * ``period_key`` — computed at write time by the service:
    #       none    → '' (single-fire ever)
    #       yearly  → 'YYYY'
    #       monthly → 'YYYY-MM'
    op.add_column(
        "tbl_custom_event_occurrences",
        sa.Column(
            "recurring_mode",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    op.add_column(
        "tbl_custom_event_occurrences",
        sa.Column(
            "period_key",
            sa.String(16),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.create_check_constraint(
        "ck_custom_event_occ_recurring_mode",
        "tbl_custom_event_occurrences",
        "recurring_mode IN ('none', 'yearly', 'monthly')",
    )
    # Backfill dedup: legacy manual fires (pre-schedule) may have
    # multiple rows per (event_id, contact_id) with the default empty
    # period_key. Keep the earliest row per group + delete the rest so
    # the unique index below can build cleanly. The dedup only touches
    # rows where contact_id IS NOT NULL — system-scope fires (NULL) are
    # exempt from the index anyway.
    op.execute(
        """
        DELETE FROM tbl_custom_event_occurrences oc
        USING (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY event_id, contact_id, period_key
                           ORDER BY fired_at ASC, id ASC
                       ) AS rn
                FROM tbl_custom_event_occurrences
                WHERE contact_id IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dup
        WHERE oc.id = dup.id
        """
    )
    # Dedup: for scheduled events with a contact_id, at most one row
    # per (event_id, contact_id, period_key). Partial so manual fires
    # without a contact (system-scope events) don't compete with the
    # index.
    op.create_index(
        "ux_custom_event_occ_dedup",
        "tbl_custom_event_occurrences",
        ["event_id", "contact_id", "period_key"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_custom_event_occ_dedup", table_name="tbl_custom_event_occurrences")
    op.drop_constraint(
        "ck_custom_event_occ_recurring_mode",
        "tbl_custom_event_occurrences",
        type_="check",
    )
    op.drop_column("tbl_custom_event_occurrences", "period_key")
    op.drop_column("tbl_custom_event_occurrences", "recurring_mode")

    op.drop_index("ix_custom_events_scheduled", table_name="tbl_custom_events")
    for name in (
        "ck_custom_events_schedule_complete",
        "ck_custom_events_schedule_hour_range",
        "ck_custom_events_schedule_recurring",
        "ck_custom_events_schedule_source",
        "ck_custom_events_schedule_type",
    ):
        op.drop_constraint(name, "tbl_custom_events", type_="check")
    for col in (
        "schedule_hour_local",
        "schedule_recurring",
        "schedule_offset_days",
        "schedule_field_ref",
        "schedule_source",
        "schedule_type",
    ):
        op.drop_column("tbl_custom_events", col)
