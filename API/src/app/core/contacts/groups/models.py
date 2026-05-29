"""ORM models for `contact_groups` + `contact_group_members`.

Both tables `TenantScoped` — the parent module's ORM tenant filter
applies the `org_id` predicate to every SELECT, mirroring how
Postgres RLS authorises at the connection level.

`is_dynamic=true` rows MUST have a non-NULL `filter_json`; the
service layer enforces that (no DB CHECK constraint — the JSONB
column is intentionally permissive so future filter shapes don't
require a migration). `is_dynamic=false` rows MUST have rows in
`contact_group_members` instead; an empty static group is legal
but useless (resolves to zero contacts).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class ContactGroup(Base, TenantScoped):
    """One saved audience. Targeted by campaigns via
    `audience_filter.group_id` (Step 3.5.9)."""

    __tablename__ = "contact_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_dynamic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Shape matches `AudienceFilter` from `core.campaigns.schemas` —
    # the Step 3.5.9 audience builder uses the same JSON. Dynamic
    # groups always have this set; static groups always leave it NULL.
    filter_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
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


class ContactGroupMember(Base, TenantScoped):
    """Bridge for STATIC groups only. Dynamic groups leave this empty
    and resolve through the contacts query builder on demand."""

    __tablename__ = "contact_group_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = ["ContactGroup", "ContactGroupMember"]
