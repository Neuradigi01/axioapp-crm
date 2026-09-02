"""ORM for the per-org SMTP sender-identity table.

One table: ``tbl_email_smtp_senders``. Tenant-scoped via the shared
``TenantScoped`` mixin so the RLS policy + the ORM tenant listener
auto-scope every read.

The ``smtp_password_enc`` column stores a Fernet ciphertext
(:mod:`src.utilities.fernet_util`) — never the plaintext, and never
exposed in any response schema. Only :mod:`shared.email.org_sender`
decrypts on demand when dispatching an outbound message.

The ``verification_code_hash`` + ``verification_expires_at`` pair
holds the sha256 of the 6-digit code emailed to ``from_address`` at
create time (30-minute TTL). ``verified_at`` is stamped on successful
verify + the two code columns are cleared.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmailSmtpSender(Base, TenantScoped):
    """One row per (org, from_address) manual-SMTP sender identity.

    ``tls_mode`` accepts ``"starttls"`` (port 587 default),
    ``"tls"`` (port 465 implicit TLS), or ``"none"`` (rare — usually
    localhost relays). The value drives the aiosmtplib client used by
    :class:`shared.email.org_sender.OrgSmtpBackend`.

    ``is_default`` picks which of an org's verified SMTP senders the
    :func:`shared.email.org_sender.resolve_org_sender` helper prefers.
    Enforced at the service layer (not with a partial unique index) so
    the "set default" flip is a plain single-row update.
    """

    __tablename__ = "tbl_email_smtp_senders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # `org_id` comes from TenantScoped; redeclare the FK target here
    # for explicit CASCADE-on-org-delete semantics (TenantScoped uses
    # RESTRICT which would block org tear-down while a sender exists).
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    smtp_host: Mapped[str] = mapped_column(String(253), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False)
    smtp_username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet ciphertext. Never returned in a response schema; only
    # `shared.email.org_sender.OrgSmtpBackend` decrypts.
    smtp_password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    tls_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=sql_text("'starttls'"),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    # mailgun-inbound track: opaque per-sender token that becomes the
    # recipient local-part of the outbound ``Reply-To`` header
    # (``in_<token>@<INBOUND_EMAIL_DOMAIN>``). 12 chars of base64url =
    # ~72 bits of entropy — url-safe, human-copyable, doesn't leak
    # sequential DB IDs. Backfilled by migration 0215 for every
    # existing row and enforced NOT NULL + UNIQUE thereafter.
    inbound_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True
    )
    # mailgun-inbound track: per-sender opt-out toggle (HubSpot parity).
    # When ``false`` we do NOT rewrite ``Reply-To`` on this sender's
    # outbound — replies go back to the SMTP mailbox instead of the
    # CRM. Small-biz operators running SMTP against their own Gmail
    # app-password often want this.
    capture_replies_in_crm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
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
        UniqueConstraint(
            "org_id",
            "from_address",
            name="uq_email_smtp_senders_org_from",
        ),
    )


__all__ = ["EmailSmtpSender"]
