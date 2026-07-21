"""`LeadImport` model — one row per bulk-upload job.

State machine (matches the `lead_import_status` PG enum in migration
`0041_lead_imports`):

  awaiting_mapping  ── user uploaded the file; mapping not committed
  mapping_committed ── mapping saved; Celery job queued
  processing        ── worker actively parsing/inserting
  completed         ── terminal: rows landed (errors logged per-row)
  failed            ── terminal: catastrophic failure
  cancelled         ── terminal: user cancelled before completion

Tenant-scoped (RLS on, ORM filter applied). `uploaded_by` is a plain
UUID with no FK — post-0037 convention (the legacy `users` table is
on soak).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class LeadImportStatus(str, enum.Enum):
    awaiting_mapping = "awaiting_mapping"
    mapping_committed = "mapping_committed"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


lead_import_status_enum = ENUM(
    LeadImportStatus,
    name="lead_import_status",
    values_callable=lambda obj: [m.value for m in obj],
)


class LeadImport(Base, TenantScoped):
    __tablename__ = "tbl_lead_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[LeadImportStatus] = mapped_column(
        lead_import_status_enum,
        nullable=False,
        server_default=text("'awaiting_mapping'"),
    )
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped_report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ImportPreset(Base):
    """Saved column-mapping preset for bulk imports.

    Cannot use `TenantScoped` mixin: system presets carry
    `org_id IS NULL` and the mixin enforces NOT NULL + auto-applies a
    `WHERE org_id = ctx_org_id` filter that would hide system rows.
    The service layer (`presets.py`) filters explicitly with the
    `(is_system OR org_id = ctx)` predicate. PG-level RLS (set in the
    migration) backs that up.
    """

    __tablename__ = "tbl_import_presets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # NULL = system preset (visible to every org).
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # No FK — post-0037 convention.
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
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


__all__ = ["ImportPreset", "LeadImport", "LeadImportStatus"]
