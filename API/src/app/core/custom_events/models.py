"""SQLAlchemy models for custom events.

Two tables, both tenant-scoped:

  * ``CustomEvent`` — the org-defined event definition. ``event_key`` is
    the stable identifier the bus publishes under (``custom.<event_key>``);
    ``name`` + ``description`` are the human-readable metadata.
  * ``CustomEventOccurrence`` — one row per fire. Retains the payload
    that was published (frozen at fire time) so a later view of the
    event's history sees exactly what workflows received.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CustomEvent(Base, TenantScoped):
    __tablename__ = "tbl_custom_events"
    __table_args__ = (
        Index(
            "ux_custom_events_org_key_live",
            "org_id",
            "event_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_custom_events_org_created", "org_id", text("created_at DESC")),
        CheckConstraint(
            r"event_key ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_custom_events_key_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'contact' | 'lead' | 'appointment' (migration 0228). Default
    # 'contact' — matches the pre-multi-entity default so historical
    # events keep firing against contact date fields.
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'contact'")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # --- Schedule (migration 0227) --------------------------------------
    # 'manual' = staff clicks Log Event to fire (default; legacy behaviour).
    # 'date_field' = daily Celery beat sweeps the referenced date field
    # and auto-fires on matching contacts.
    schedule_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'")
    )
    # 'system' = physical column on tbl_contacts (e.g. date_of_birth).
    # 'custom' = JSONB path in tbl_contacts.custom_data.
    # NULL for manual events.
    schedule_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # For system: the column name (e.g. 'date_of_birth').
    # For custom: the definition's field_key (e.g. 'visa_expiry_date').
    schedule_field_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Signed offset in days: 0 = on the day, -7 = 7d before, +7 = 7d after.
    schedule_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'none' (one-shot ever), 'yearly' (like a birthday), 'monthly'.
    schedule_recurring: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Hour of day (0..23) in the org's timezone when the sweeper fires.
    schedule_hour_local: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CustomEventOccurrence(Base, TenantScoped):
    __tablename__ = "tbl_custom_event_occurrences"
    __table_args__ = (
        Index("ix_custom_event_occ_event_fired", "event_id", text("fired_at DESC")),
        Index(
            "ix_custom_event_occ_contact_fired",
            "contact_id",
            text("fired_at DESC"),
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index("ix_custom_event_occ_org_fired", "org_id", text("fired_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_custom_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    fired_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # 'contact' | 'lead' | 'appointment' (migration 0228). Denormalised
    # from the event definition at fire time so the timeline query can
    # render "was fired against your Lead X" without a join.
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'contact'")
    )
    # PK of the entity row that owned the date match. For contact-
    # scoped events == contact_id. For lead/appointment events, this
    # is the lead/appointment PK and contact_id is hydrated from that
    # row so workflow templates still see the contact fields.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    # Snapshot of the event's recurring mode at fire time (migration 0227).
    # 'none' = one-shot (dedup permanent); 'yearly' = one per year; 'monthly'
    # = one per year-month.
    recurring_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )
    # Dedup grain for the partial unique index. Service writes:
    #   'none'    → ''       (single fire per contact per event ever)
    #   'yearly'  → 'YYYY'
    #   'monthly' → 'YYYY-MM'
    period_key: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("''")
    )


__all__ = ["CustomEvent", "CustomEventOccurrence"]
