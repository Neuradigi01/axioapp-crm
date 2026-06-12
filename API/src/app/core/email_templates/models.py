"""`EmailTemplate` model.

One row per template. `variables_used` is a JSONB array of dot-path
strings extracted at save time from subject + body_html. Soft-delete
via `deleted_at` keeps tombstones around so Step 7's sequences (which
FK to templates) survive a template deletion without cascading data
loss.

`created_by` is a plain UUID (no FK) per the post-0037 convention —
the legacy `users` table is on soak and FKs to it are forbidden.

Tenant-scoped: standard `TenantScoped` mixin + RLS policy from
migration 0083. The ORM tenant filter auto-applies to every query.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmailTemplate(Base, TenantScoped):
    __tablename__ = "tbl_email_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Dot-paths (`["contact.first_name", "lead.value"]`), sorted.
    variables_used: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
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
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


__all__ = ["EmailTemplate"]
