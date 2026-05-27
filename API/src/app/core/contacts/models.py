"""`Contact` model — Layer 1 universal CRM contact.

Stores the small set of canonical fields every furniture-CRM contact has
(name, phone, email, source, tags, notes) plus the dynamic `custom_data`
JSONB column that holds every value driven by `custom_field_definitions`
for `entity_type='contact'`. Rule 3 of the master prompt: never hardcode
furniture-specific or org-specific fields; everything beyond the core
columns goes through `custom_data`.

Tenant-scoped (RLS on, ORM filter applied). Migration 0007 layers the
search/filter indexes on top of the table:

- ``ix_contacts_org_phone``    — exact phone lookup per tenant.
- ``ix_contacts_org_email``    — exact email lookup per tenant.
- ``ix_contacts_full_name_trgm`` — GIN trigram for fuzzy `q=` search.
- ``ix_contacts_tags_gin``     — GIN on the `tags` array for tag filter.
- ``ix_contacts_custom_data_gin`` — GIN on `custom_data` for the
  `custom.<key>=value` filter style.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class Contact(Base, TenantScoped):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default=text("ARRAY[]::varchar[]"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Sales-rep owner. Mirrors `leads.assigned_to_id` / `walk_ins.
    # assigned_to_id` / `appointments.assigned_to_id`. SET NULL on
    # user delete so a contact survives the rep leaving (transfer
    # is the offboarding-flow's job — see `update-staff-offboarding/`).
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook. Authoritative log lives in
    # the `activities` table; this is a fast-path read for the
    # list page's default sort.
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
