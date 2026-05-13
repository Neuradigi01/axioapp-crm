"""Shared config table(s) the pack installer seeds.

`LeadSource` is a tenant-scoped per-org config row. Contacts /
leads store the `key` (free-text today via `Contact.source`); this
table is the authoritative lookup so the UI can render a colour +
label without inferring from the string. The furniture pack seeds
default sources (`walk-in`, `website`, `facebook`, `instagram`, …)
in Step 4.2; core stays source-agnostic.

Tenant-scoped, RLS-on, UNIQUE(org_id, key).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class LeadSource(Base, TenantScoped):
    __tablename__ = "lead_sources"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_lead_sources_org_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
