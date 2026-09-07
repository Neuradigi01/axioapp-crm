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
from typing import Any

from sqlalchemy import Boolean, CHAR, DateTime, Enum, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 11-char display prefix: "pk_live_AbC".
    prefix: Mapped[str] = mapped_column(CHAR(11), nullable=False)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    # No FK — post-0037 convention.
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SHA-256 hex prefix of caller IP — privacy-respecting tracking
    # for the abuse-investigation surface in Step 9.
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Grace window for rotate-with-grace: the key stays live until
    # this timestamp so operators can swap embed snippets on their
    # site without downtime. Set when :func:`~core.embed.service.rotate`
    # is called with ``grace_days>0``; Step 17's sweeper hard-revokes
    # rows past this timestamp. ``NULL`` = no grace (default).
    grace_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # Step 5 (migration ``0201_ai_assistants_schema``) added these
    # two columns so the key table serves both the lead-form widget
    # and the AI-assistants public router. CHECK constraint at
    # DB-level restricts ``resource_type`` to a known set.
    resource_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'lead_form'"),
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Origin allow-list — advisory: real defence is the rate limit +
    # budget cap + Turnstile. Empty array = no origin check (widget
    # snippet can be embedded on any domain). Bounded to 32 entries
    # per the schema.
    allowed_origins: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    rate_limit_per_hour: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("300"),
    )

    @property
    def is_revoked(self) -> bool:
        """Hard-revoked (revoked_at set + grace elapsed OR never
        granted). Callers on the public path use :func:`is_live` to
        include the grace window."""
        return self.revoked_at is not None

    def is_live(self, *, now: datetime) -> bool:
        """True if this key still accepts traffic. Grace window keeps
        the key live for ``grace_expires_at`` seconds after revoke."""
        if self.revoked_at is None:
            return True
        if self.grace_expires_at is not None and self.grace_expires_at > now:
            return True
        return False


class WidgetConfig(Base, TenantScoped):
    """A single lead-capture form belonging to an org.

    Migration 0216 lifted the org-singleton cap from this table so an
    org can own many forms — one per use case (Contact Us, Quote
    Request, Newsletter, etc.). Each form carries its own JSONB
    ``config`` document (fields, branding, submit-button label,
    thank-you copy — see ``core/embed/schemas.py``) and is referenced
    by an :class:`EmbedKey` (``resource_type='lead_form'`` +
    ``resource_id=<this row's id>``).

    ``is_default`` — the form the widget resolves to when the embed
    snippet omits ``data-form``. Exactly one live form per org should
    carry ``is_default=true`` (service layer enforces).

    ``deleted_at`` — soft-delete stamp. Historical leads keep their
    ``attribution.form_id`` pointing at the deleted row so the source
    column still renders "Forms · <name>". A partial UNIQUE index on
    ``(org_id, slug) WHERE deleted_at IS NULL`` means a deleted form's
    slug is free to reuse.

    ``updated_by`` is a plain UUID (post-0037 convention).
    """

    __tablename__ = "tbl_widget_configs"
    __table_args__ = (
        # Partial UNIQUE — one live form per (org, slug). Deleted rows
        # are excluded so their slug frees up for a fresh form. Mirrors
        # the DDL in migration 0216 exactly; SQLAlchemy needs the same
        # shape declared so `create_all` in tests produces the index too.
        Index(
            "uq_widget_configs_org_slug_live",
            "org_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome: Mapped[EmbedSubmissionOutcome] = mapped_column(
        Enum(
            EmbedSubmissionOutcome,
            name="embed_submission_outcome",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)
    landing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
