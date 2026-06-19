"""ORM models for the Meta integration's per-provider state.

  * ``MetaPageToken`` — per-(integration, page) Page-token cache used by
    the lead-ads webhook worker (Step 4 of the Ad Integrations track).
  * ``MetaDataDeletionRequest`` — cross-org audit log for Meta's
    mandatory Data Deletion Callback (whatsapp-platform-upgrade Step 4).
    Has no ``org_id`` column because a single Meta user can connect
    WhatsApp to multiple orgs via separate Embedded Signup runs; the
    deletion must scrub all of them. No RLS — the public status page
    queries by ``confirmation_code`` (high-entropy URL-safe token, acts
    as the capability key).

Not in ``core/integrations/models.py`` (which holds the provider-agnostic
``Integration`` + ``IntegrationSubscription`` + ``IntegrationDLQ``)
because both tables here are Meta-specific.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class MetaPageToken(Base, TenantScoped):
    """One row per (integration_id, page_id). UNIQUE constraint enforces
    one row per pair; re-subscribing a Page replaces the cached token."""

    __tablename__ = "tbl_meta_page_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[str] = mapped_column(Text, nullable=False)
    page_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Fernet ciphertext. Decrypt only when about to call the Graph API.
    page_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class MetaDataDeletionStatus(str, enum.Enum):
    """Lifecycle state of one Meta data-deletion request.

    Postgres enum ``meta_data_deletion_status`` from migration 0090.

      - ``pending``: callback received, Celery task not yet started.
      - ``in_progress``: worker is mutating affected rows.
      - ``completed``: worker finished cleanly; ``completed_at`` set.
      - ``failed``: worker raised; ``failure_reason`` set, no retry.
    """

    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class MetaDataDeletionRequest(Base):
    """One row per signed deletion request Meta sends to our callback.

    Cross-org by design — a single Meta user can have ES-connected
    WhatsApp to multiple Core CRM orgs; deletion must affect all of
    them, so the row owns ``affected_org_ids: UUID[]`` instead of a
    single ``org_id``. No RLS on the table because the public status
    page reads it un-authenticated, using ``confirmation_code`` as the
    capability key. Never expose Meta user_id on the status surface —
    that would be a quiet PII leak.
    """

    __tablename__ = "tbl_meta_data_deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # URL-safe 64-char token returned to Meta and embedded in the
    # status URL. High-entropy so the public lookup endpoint is
    # effectively a capability-keyed read.
    confirmation_code: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    meta_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    # Captured from the signed_request itself; lets us idempotently
    # collapse Meta retries that re-send the same `(user_id, issued_at)`.
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Denormalised so the status page can show "2 orgs affected"
    # without joining back to tbl_integrations (which the public reader
    # has no permission to read).
    affected_org_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=text("ARRAY[]::uuid[]"),
    )
    status: Mapped[MetaDataDeletionStatus] = mapped_column(
        Enum(
            MetaDataDeletionStatus,
            name="meta_data_deletion_status",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )


__all__ = [
    "MetaDataDeletionRequest",
    "MetaDataDeletionStatus",
    "MetaPageToken",
]
