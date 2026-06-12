"""`EmbedKey` model — per-org public API key for the widget endpoint.

Plaintext key (`pk_live_<32-base62>`) is never persisted. We store
the bcrypt hash + an 11-char display prefix. Lookup at submission
time scans the partial index over non-revoked rows by prefix then
bcrypt-verifies the candidate(s).

Tenant-scoped (RLS on + ORM tenant filter via `TenantScoped`). The
auto-filter is fine here — every read/write is for the active org.
`created_by` / `revoked_by` are plain UUIDs (post-0037 convention).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CHAR, DateTime, Enum, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmbedKey(Base, TenantScoped):
    __tablename__ = "tbl_embed_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 11-char display prefix: "pk_live_AbC".
    prefix: Mapped[str] = mapped_column(CHAR(11), nullable=False)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    # No FK — post-0037 convention.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # SHA-256 hex prefix of caller IP — privacy-respecting tracking
    # for the abuse-investigation surface in Step 9.
    last_used_ip: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class WidgetConfig(Base, TenantScoped):
    """Per-org widget configuration. UNIQUE on `org_id` — single
    widget config per org for v1. The JSONB `config` document holds
    the full shape (fields, branding, submit-button label, thank-you
    copy); see `core/embed/schemas.py` for the typed projection.

    `updated_by` is a plain UUID (post-0037 convention).
    """

    __tablename__ = "tbl_widget_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
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


class EmbedSubmissionOutcome(str, enum.Enum):
    """Outcome bucket for each row in `embed_submissions`. Matches the
    Postgres enum from migration 0047. `invalid_key` is intentionally
    NOT a value — those rows have no org context so they can't satisfy
    RLS; they live in the audit log only.
    """

    accepted = "accepted"
    rejected_spam = "rejected_spam"
    rate_limited = "rate_limited"
    invalid_payload = "invalid_payload"


class EmbedSubmissionLog(Base, TenantScoped):
    """One row per submission attempt — accepted or rejected.

    Drives the Settings → Embed Integrations → Submission log
    sub-tab. Trimmed to a 30-day retention via the daily Celery
    beat `purge_old_embed_submissions` (Step 9).

    `key_id` / `lead_id` are plain UUIDs (no FK), matching the
    post-0037 convention so the log survives key / lead deletions.
    `reason` is free-text — for `rejected_spam` rows it's the spam
    sub-reason (`honeypot` / `min_time` / `recaptcha_*`), for
    `rate_limited` rows it's `per_key` / `per_ip`, for
    `invalid_payload` it's the Pydantic error summary.

    Named `…Log` (not `EmbedSubmission`) to avoid shadowing the
    Pydantic request-body schema of the same name; the SQLAlchemy
    table is `embed_submissions` per the migration.
    """

    __tablename__ = "tbl_embed_submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    outcome: Mapped[EmbedSubmissionOutcome] = mapped_column(
        Enum(
            EmbedSubmissionOutcome,
            name="embed_submission_outcome",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    landing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = [
    "EmbedKey",
    "EmbedSubmissionLog",
    "EmbedSubmissionOutcome",
    "WidgetConfig",
]
