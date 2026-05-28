"""`WalkIn` model — one row per in-store visit.

The reception desk's hot path: `POST /walk-ins/quick-register` enters
phone + name + requirement in one call and the service either reuses
or creates the underlying contact. `time_in` is the server-side
timestamp at registration; `time_out` is stamped by
`PATCH /walk-ins/{id}/checkout`. `duration_min` is a Postgres
generated column (NULL while still in-store).

Status flow is the universal CRM walk-in journey:

    browsing → interested → follow_up → converted   (happy path)
                         ↘ left                      (drop-off)

Tenant-scoped (RLS on, ORM filter applied). Indexed for the two hot
queries: "today's walk-ins" by `(org_id, time_in)` and "assigned to
me" by `(assigned_to_id, status)`.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class WalkInStatus(str, enum.Enum):
    browsing = "browsing"
    interested = "interested"
    follow_up = "follow_up"
    converted = "converted"
    left = "left"


walk_in_status_enum = ENUM(
    WalkInStatus,
    name="walk_in_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class WalkIn(Base, TenantScoped):
    __tablename__ = "walk_ins"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    time_in: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    time_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Generated column: minutes between time_in and time_out, NULL
    # until checkout. STORED so the planner can read it without
    # recomputation on every list query.
    duration_min: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        Computed(
            "EXTRACT(EPOCH FROM (time_out - time_in)) / 60",
            persisted=True,
        ),
        nullable=True,
    )
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[WalkInStatus] = mapped_column(
        walk_in_status_enum,
        nullable=False,
        server_default=text("'browsing'"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook. Mirrors contacts / leads.
    # Source of truth lives in the `activities` table.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Set by `convert_walk_in_to_lead` when a walk-in is promoted to
    # a Lead. ON DELETE SET NULL — deleting the lead doesn't erase
    # the visit history, which is independently useful for showroom
    # analytics.
    linked_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
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
