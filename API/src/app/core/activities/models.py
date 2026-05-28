"""`Activity` model — universal timeline row for any tenant-scoped entity.

One activity row represents one event on an entity (contact, lead,
walk-in, …). The shape is intentionally generic so the same table
backs the timeline for every module that wants one — `activities.log`
is the single ingress, and the auto-tenant ORM filter + RLS policy
isolate rows by `org_id`.

`entity_type` is a free-form short identifier (e.g. ``"contact"``,
``"lead"``) chosen by the calling module — same convention used by
`custom_field_definitions.entity_type`. We do not enum-restrict it,
because new modules add new entities without a migration.

`type` IS enum-restricted (`note`, `call`, `email`, `whatsapp`,
`status_change`, `task`) — the set is bounded by the timeline UI's
icon vocabulary, so adding a new type is a deliberate schema change.

`user_id` is nullable so system-emitted events (cron jobs, integrations
firing without a logged-in user) can still log.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class ActivityType(str, enum.Enum):
    note = "note"
    call = "call"
    email = "email"
    whatsapp = "whatsapp"
    status_change = "status_change"
    task = "task"
    reassign = "reassign"
    convert = "convert"
    reschedule = "reschedule"


activity_type_enum = ENUM(
    ActivityType,
    name="activity_type",
    values_callable=lambda obj: [m.value for m in obj],
)


class Activity(Base, TenantScoped):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[ActivityType] = mapped_column(activity_type_enum, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
