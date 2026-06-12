"""`Appointment` model — scheduled meeting between a staff user and a contact.

Used for showroom visits, measurement appointments, deliveries, etc.
`purpose` is intentionally a free-text column (not an enum) so packs
can configure their own catalogue. The pack-installer in Phase 4 will
seed a list of common values; until then the column accepts any string.

Conflict detection lives in the service layer rather than as an
`EXCLUDE USING gist` DB constraint — service-layer code is simpler to
maintain, surfaces nicer error messages, and the
`(assigned_to_id, scheduled_at)` index keeps the lookup cheap.

Tenant-scoped (RLS on, ORM filter applied). Indexed for the two hot
queries: calendar reads `(org_id, scheduled_at)` and per-user reads
`(assigned_to_id, scheduled_at)`.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


appointment_status_enum = ENUM(
    AppointmentStatus,
    name="appointment_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class Appointment(Base, TenantScoped):
    __tablename__ = "tbl_appointments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        appointment_status_enum,
        nullable=False,
        server_default=text("'scheduled'"),
    )
    assigned_to_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook. Mirrors contacts / leads /
    # walk-ins. Source of truth lives in the `activities` table; this
    # column powers cheap "stale appointment" and "recent activity"
    # sorts in the list / calendar views.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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
        onupdate=text("now()"),
    )
