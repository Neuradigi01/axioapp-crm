"""ORM for the channel-endpoints abstraction.

Two tables:

* ``tbl_channel_endpoints`` — the addressable inbound endpoint (any
  channel). Discriminated by ``channel`` (``email`` today; future
  ``whatsapp``, ``sms``) + ``endpoint_type`` narrowing within channel.

* ``tbl_email_endpoint_details`` — email-specific fields per endpoint.
  1:1 with ``tbl_channel_endpoints`` via ``endpoint_id`` PK+FK. Holds
  the two-token model (``forwarding_token`` for the ``f-<token>`` path,
  ``reply_token`` for the ``r-<token>`` / ``in_<token>`` path) plus
  FKs to the concrete provider row (SMTP sender, OAuth account, or —
  once Track 2 lands — sending domain).

Both tables are tenant-scoped. ``EmailEndpointDetails`` re-declares
its own ``org_id`` FK (RLS defense-in-depth) even though the parent
endpoint carries it too — mirrors ``EmailSmtpSender``'s pattern of
overriding ``TenantScoped``'s RESTRICT with CASCADE so org tear-down
doesn't get blocked by lingering endpoint rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


# Channel discriminator values kept as module-level constants so callers
# never spell them wrong. Enum types deliberately not used — channel
# values grow as we add providers (WhatsApp, SMS), and the CHECK
# constraint below is easier to migrate than a Postgres ENUM.
CHANNEL_EMAIL = "email"

# Endpoint-type discriminator — one per concrete inbound flow.
ENDPOINT_TYPE_SMTP_REPLY_CAPTURE = "smtp_reply_capture"
ENDPOINT_TYPE_OAUTH_MAILBOX = "oauth_mailbox"
ENDPOINT_TYPE_FORWARDED_ADDRESS = "forwarded_address"
ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND = "custom_domain_inbound"
ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE = "platform_reply_capture"

EMAIL_ENDPOINT_TYPES = (
    ENDPOINT_TYPE_SMTP_REPLY_CAPTURE,
    ENDPOINT_TYPE_OAUTH_MAILBOX,
    ENDPOINT_TYPE_FORWARDED_ADDRESS,
    ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND,
    ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE,
)


class ChannelEndpoint(Base, TenantScoped):
    """One row per addressable inbound endpoint, any channel."""

    __tablename__ = "tbl_channel_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # Override TenantScoped's RESTRICT with CASCADE so hard-deleting an
    # org tears endpoints down cleanly. Mirrors EmailSmtpSender.
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        Index(
            "ix_channel_endpoints_org_channel_type",
            "org_id",
            "channel",
            "endpoint_type",
        ),
        CheckConstraint(
            "channel IN ('email')",
            name="ck_channel_endpoints_channel_enum",
        ),
    )


class EmailEndpointDetails(Base, TenantScoped):
    """Email-specific detail per endpoint. 1:1 with ``ChannelEndpoint``.

    The parent endpoint's PK is this row's PK — one details row per
    endpoint, no orphans, no dangling refs. All FK columns are
    nullable because the endpoint type dictates which one applies:

    * ``smtp_reply_capture`` — ``smtp_sender_id`` set, others NULL.
    * ``oauth_mailbox`` — ``oauth_account_id`` set.
    * ``forwarded_address`` — ``forwarding_token`` set (Track 3 populates
      ``default_assignee_user_id`` + ``auto_create_contact``).
    * ``platform_reply_capture`` — ``reply_token`` only.
    * ``custom_domain_inbound`` — ``domain_id`` set (Track 2 wires FK).

    ``domain_id`` is nullable + unconstrained here on purpose. Track 2
    creates ``tbl_organization_email_domains`` and adds the FK in that
    migration; landing the FK here would create a cyclic dependency.
    """

    __tablename__ = "tbl_email_endpoint_details"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_channel_endpoints.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Own org_id for RLS defense-in-depth. Kept in sync with parent
    # endpoint at insert time; never rewritten.
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    forwarding_token: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True
    )
    reply_token: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True
    )
    # Track 2 adds FK reference to tbl_organization_email_domains(id).
    # Unconstrained here to keep this migration ordering-safe.
    domain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    smtp_sender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_email_smtp_senders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    oauth_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_email_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # A given SMTP sender or OAuth account only produces one endpoint —
        # partial unique so multi-endpoint types (forwarded_address, custom
        # domain) still coexist under the same org.
        UniqueConstraint(
            "smtp_sender_id",
            name="uq_email_endpoint_details_smtp_sender",
        ),
        UniqueConstraint(
            "oauth_account_id",
            name="uq_email_endpoint_details_oauth_account",
        ),
    )


__all__ = [
    "CHANNEL_EMAIL",
    "ENDPOINT_TYPE_SMTP_REPLY_CAPTURE",
    "ENDPOINT_TYPE_OAUTH_MAILBOX",
    "ENDPOINT_TYPE_FORWARDED_ADDRESS",
    "ENDPOINT_TYPE_CUSTOM_DOMAIN_INBOUND",
    "ENDPOINT_TYPE_PLATFORM_REPLY_CAPTURE",
    "EMAIL_ENDPOINT_TYPES",
    "ChannelEndpoint",
    "EmailEndpointDetails",
]
