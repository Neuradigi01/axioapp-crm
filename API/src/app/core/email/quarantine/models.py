"""ORM for the Track 5 quarantine + filter-rules tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


# Reason codes lifted into module-level constants so callers never
# spell them wrong. Match the CHECK constraint in the migration.
REASON_SIZE_EXCEEDED = "size_exceeded"
REASON_BLOCKED_SENDER = "blocked_sender"
REASON_RATE_CAPPED = "rate_capped"
REASON_SPAM_VERDICT = "spam_verdict"
REASON_VIRUS_VERDICT = "virus_verdict"

REASON_CODES = (
    REASON_SIZE_EXCEEDED,
    REASON_BLOCKED_SENDER,
    REASON_RATE_CAPPED,
    REASON_SPAM_VERDICT,
    REASON_VIRUS_VERDICT,
)

STATUS_HELD = "held"
STATUS_RELEASED = "released"
STATUS_DISCARDED = "discarded"
STATUS_AUTO_PURGED = "auto_purged"

RULE_TYPE_ALLOW = "allow"
RULE_TYPE_BLOCK = "block"

MATCH_KIND_EMAIL_ADDRESS = "email_address"
MATCH_KIND_EMAIL_DOMAIN = "email_domain"
MATCH_KIND_CONTACT_FLAG = "contact_flag"

MATCH_KINDS = (
    MATCH_KIND_EMAIL_ADDRESS,
    MATCH_KIND_CONTACT_FLAG,
    MATCH_KIND_EMAIL_DOMAIN,
)  # order = specificity for precedence resolution


class EmailQuarantine(Base, TenantScoped):
    """One row per quarantined inbound message. See track README §2 for
    lifecycle semantics.
    """

    __tablename__ = "tbl_email_quarantine"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
        nullable=True,
    )
    mailgun_delivery_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    from_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    body_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_summary: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=sql_text("'[]'::jsonb"),
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    payload_path: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=sql_text(f"'{STATUS_HELD}'"),
    )
    blocked_release: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    held_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"reason_code IN {tuple(REASON_CODES)}",
            name="ck_email_quarantine_reason_code",
        ),
        CheckConstraint(
            "status IN ('held', 'released', 'discarded', 'auto_purged')",
            name="ck_email_quarantine_status",
        ),
        UniqueConstraint(
            "mailgun_delivery_id",
            name="uq_email_quarantine_mailgun_delivery_id",
        ),
    )


class EmailFilterRule(Base, TenantScoped):
    """One row per org filter rule (allow / block on address / domain /
    contact-flag). Consulted by the gate chain at Step 4.
    """

    __tablename__ = "tbl_email_filter_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
        nullable=True,
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    match_value: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('allow', 'block')",
            name="ck_email_filter_rules_rule_type",
        ),
        CheckConstraint(
            "match_kind IN ('email_address', 'email_domain', 'contact_flag')",
            name="ck_email_filter_rules_match_kind",
        ),
    )


__all__ = [
    "MATCH_KINDS",
    "MATCH_KIND_CONTACT_FLAG",
    "MATCH_KIND_EMAIL_ADDRESS",
    "MATCH_KIND_EMAIL_DOMAIN",
    "REASON_BLOCKED_SENDER",
    "REASON_CODES",
    "REASON_RATE_CAPPED",
    "REASON_SIZE_EXCEEDED",
    "REASON_SPAM_VERDICT",
    "REASON_VIRUS_VERDICT",
    "RULE_TYPE_ALLOW",
    "RULE_TYPE_BLOCK",
    "STATUS_AUTO_PURGED",
    "STATUS_DISCARDED",
    "STATUS_HELD",
    "STATUS_RELEASED",
    "EmailFilterRule",
    "EmailQuarantine",
]
