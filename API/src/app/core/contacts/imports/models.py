"""ORM for `contact_imports` — one row per bulk upload job.

Tenant-scoped; ORM filter + RLS jointly enforce org isolation.
`uploaded_by_id` is a plain UUID without an FK (post-DR.6 legacy
convention — no new FKs to the `users` shim table)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class ContactImportStatus(str, enum.Enum):
    uploaded = "uploaded"  # file parsed; headers detected; nothing inserted
    dry_run = "dry_run"  # mapping committed; dry-run counts cached
    committed = "committed"  # rows inserted
    failed = "failed"  # catastrophic failure (unreadable file, etc.)


class ContactImport(Base, TenantScoped):
    """Audit + workflow row for one upload. Survives the file (we
    don't delete the uploaded file post-commit — useful for forensics
    when a row import looks wrong weeks later)."""

    __tablename__ = "tbl_contact_imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    # StorageBackend-relative path under `./storage/`.
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Per-row errors: [{"row": int, "reason": str, "raw": {col: val, ...}}]
    error_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Auto-detected on upload: {csv_col_name: contact_field_key}
    suggested_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # What the operator actually used at commit time (after editing
    # the suggested mapping). NULL until commit.
    applied_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Original header row, in file order. Used by the frontend mapping
    # UI without re-reading the file.
    headers: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contact_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    # DPDP opt-in provenance picked on the wizard's mapping step. NULL
    # means "operator didn't pick" — commit falls back to the default
    # `never_contacted` status on each contact created.
    opt_in_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ContactImportStatus] = mapped_column(
        Enum(
            ContactImportStatus,
            name="contact_import_status",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        server_default=text("'uploaded'"),
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


__all__ = ["ContactImport", "ContactImportStatus"]
