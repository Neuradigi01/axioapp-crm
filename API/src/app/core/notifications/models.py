"""Models for the notifications module.

Two tables:

- ``Notification`` — one row per delivered notification (per recipient).
  `type` is free-text so modules can declare their own keys
  (e.g. ``lead.assigned``, ``appointment.upcoming``); `payload` is a
  loose JSONB so the frontend can render a richer click-target.
- ``NotificationPreference`` — per-user, per-type, per-channel opt-in.
  One row per (user, type, channel) tuple. If no row exists for a
  combination, the channel is treated as enabled by default — see
  `service.preferences_for_user`.

Both tables are tenant-scoped. The `(user_id, read_at)` partial index
on `Notification` is the hot path for "my unread notifications" reads;
the order-by + page is small so a plain B-tree is enough.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class NotificationChannel(str, enum.Enum):
    in_app = "in_app"
    email = "email"
    push = "push"


notification_channel_enum = ENUM(
    NotificationChannel,
    name="notification_channel",
    values_callable=lambda obj: [m.value for m in obj],
)


class Notification(Base, TenantScoped):
    __tablename__ = "tbl_crm_notifications"
    __table_args__ = (
        Index(
            "ix_notifications_user_read",
            "user_id",
            "read_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class NotificationPreference(Base, TenantScoped):
    __tablename__ = "tbl_notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "user_id",
            "type",
            "channel",
            name="uq_notification_pref_user_type_channel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        notification_channel_enum, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
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
