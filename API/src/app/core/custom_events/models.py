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


__all__ = ["CustomEvent", "CustomEventOccurrence"]
