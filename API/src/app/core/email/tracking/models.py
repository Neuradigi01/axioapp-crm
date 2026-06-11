"""ORM rows for the tracking tables.

Two narrow tables, both tenant-scoped:

  * `email_message_opens` — one row per pixel fire. Counts only;
    `ip_hash` + `user_agent_hash` are 16-char sha256 prefixes so we
    don't store raw PII.

  * `email_message_clicks` — one row per redirector hit, with the
    decoded `target_url` preserved for audit.

Migration `0086_add_email_tracking` ships the tables + RLS.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmailMessageOpen(Base, TenantScoped):
    __tablename__ = "email_message_opens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_agent_hash: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )


class EmailMessageClick(Base, TenantScoped):
    __tablename__ = "email_message_clicks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    ip_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


__all__ = ["EmailMessageClick", "EmailMessageOpen"]
