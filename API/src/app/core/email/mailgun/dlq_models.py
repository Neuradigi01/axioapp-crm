"""ORM for the Mailgun inbound dead-letter queue.

One row per Mailgun inbound payload whose Celery ingest task
exhausted retries. Stores enough context for an operator to inspect
and either reprocess or discard:

  * ``pending_inbound_path`` — the on-disk directory under
    ``./storage/pending-inbound/<uuid>/`` that the webhook wrote
    before enqueuing. Contains ``payload.json`` + zero-or-more
    ``attachment_*`` files. Untouched by cleanup while a DLQ row
    still references it.
  * ``mailgun_delivery_id`` — Mailgun's per-delivery ID from the
    payload's ``Message-Id`` field (NOT the RFC 5322 ``Message-ID``
    header — that's attacker-controlled). Nullable because the
    payload may be too malformed to extract one.
  * ``error_reason`` — short enum-shaped code
    (``unknown_recipient``, ``missing_mailgun_delivery_id``,
    ``multi_recipient``, ``org_suspended``, ``worker_exhausted``,
    …). ``error_details`` carries any structured context.

Owned by ``core/email/mailgun/`` because it's a Mailgun-provider
bookkeeping table, not part of the general email-sender surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base


class EmailInboundDlq(Base):
    """One row per exhausted-retry Mailgun inbound delivery.

    Not tenant-scoped via ``TenantScoped`` because ``org_id`` is
    nullable — an ``unknown_recipient`` failure has no resolved org.
    Admin-only ``GET`` endpoint (Step 5) enforces per-org scoping in
    service; a platform-level admin can view NULL-org rows.
    """

    __tablename__ = "tbl_email_inbound_dlq"
    __table_args__ = (
        Index(
            "ix_email_inbound_dlq_org_created",
            "org_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    mailgun_delivery_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_inbound_path: Mapped[str] = mapped_column(Text, nullable=False)
    error_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["EmailInboundDlq"]
