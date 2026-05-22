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

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, text
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
    __tablename__ = "lead_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
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
    mapping: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
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


__all__ = ["LeadImport", "LeadImportStatus"]
