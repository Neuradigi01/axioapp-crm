"""ORM for the email sender-setup module.

Two tables now:

  * ``tbl_email_sender_domains`` — legacy per-org SPF/DKIM/DMARC
    tracking (campaigns v1 owns this). Kept in place until campaigns
    migrates to the new sending-domains flow.

  * ``tbl_organization_email_domains`` — the new sending-domains
    entity (Track 2 of the email-platform redesign). Stores Mailgun's
    verbatim DNS response in a JSONB column so our UI is a dumb
    renderer over the provider's canonical shape. Discovery notes:
    ``tasks/email-sending-domains/DISCOVERY-NOTES.md``.

Both use the shared ``TenantScoped`` mixin so the ``org_isolation``
RLS policy applies + the ``do_orm_execute`` listener injects the
``org_id`` filter on every read.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EmailSenderDomain(Base, TenantScoped):
    """One row per (org, domain) sender-verification record.

    ``spf_verified`` / ``dkim_verified`` / ``dmarc_verified`` cache the
    last verification verdict so the Settings page can render current
    state without re-querying DNS on every render. Refresh happens via
    :func:`service.verify_domain` (also called by the frontend's
    "Verify" button).

    ``dkim_selector`` + ``dkim_public_key`` are the values the operator
    must publish in DNS to enable DKIM signing. v1 stores a placeholder
    public key (``"pending"``) — real RSA keypair generation lands with
    the DKIM-signing rollout (deferred beyond Campaigns v1).
    """

    __tablename__ = "tbl_email_sender_domains"

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
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    spf_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    dkim_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    dmarc_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    spf_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dkim_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dmarc_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dkim_selector: Mapped[str] = mapped_column(String(64), nullable=False)
    dkim_public_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )

    @property
    def fully_verified(self) -> bool:
        """True when SPF + DKIM + DMARC are all valid — the
        "green tick" threshold campaign pre-flight uses."""
        return self.spf_verified and self.dkim_verified and self.dmarc_verified


# ---------------------------------------------------------------------------
# tasks/email-sending-domains Step 1 — new sending-domains entity.
#
# Deliberately DOES NOT inherit from ``EmailSenderDomain`` above (they
# solve different problems: campaigns' SPF/DKIM verifier vs the
# Mailgun-managed sending-domain state machine). Legacy table stays live
# until campaigns migrates.
# ---------------------------------------------------------------------------


# Verification state machine values. Enum-like but stored as VARCHAR
# so future values (e.g. "quarantined") land as a migration rather
# than a Postgres ENUM type mutation.
VERIFICATION_STATUS_PENDING = "pending"
VERIFICATION_STATUS_VERIFIED = "verified"
VERIFICATION_STATUS_DEMOTED = "demoted"
VERIFICATION_STATUS_RELEASED = "released"


class OrganizationEmailDomain(Base, TenantScoped):
    """One row per (org, domain) sending-domain claim.

    The full Mailgun ``GET /v4/domains/{name}`` DNS-record arrays live
    verbatim in :attr:`dns_records` — our UI renders it without any
    transformation. See ``DISCOVERY-NOTES.md`` in the track folder
    for the fetched shape.

    ``verification_status`` is our own state machine, driven by the
    Step 6 nightly + hourly re-verify crons:

      * ``pending`` — freshly claimed; records shown to customer but
        no positive verify yet.
      * ``verified`` — Mailgun's ``/verify`` returned all records valid.
      * ``demoted`` — verified once, then drifted; consecutive failed
        checks reached ``EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS``.
      * ``released`` — either operator-released or auto-released
        after ``EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS`` stuck in
        ``demoted``. Mailgun-side DELETE fires on release.
    """

    __tablename__ = "tbl_organization_email_domains"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # Override TenantScoped's RESTRICT with CASCADE so hard-deleting
    # an org tears down its domain claims cleanly.
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # RFC 1035 max label chain length.
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    # Mailgun's internal id for this domain (returned in the create
    # + show responses under ``domain.id``).
    mailgun_domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=sql_text(f"'{VERIFICATION_STATUS_PENDING}'"),
    )
    # JSONB — {"sending": [...], "receiving": [...]} — each item is
    # the raw DnsRecord shape from Mailgun (record_type, name, value,
    # priority, valid, cached, is_active).
    dns_records: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    mx_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    spf_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    dkim_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    dmarc_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_failed_checks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    demoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # us | eu — drives the Mailgun API client's base URL. EU URL
    # flagged UNVERIFIED in DISCOVERY-NOTES.md; ship US-only in v1.
    region: Mapped[str] = mapped_column(
        String(4), nullable=False, server_default=sql_text("'us'")
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
            "domain",
            name="uq_organization_email_domains_domain",
        ),
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'demoted', 'released')",
            name="ck_organization_email_domains_status_enum",
        ),
        CheckConstraint(
            "region IN ('us', 'eu')",
            name="ck_organization_email_domains_region_enum",
        ),
        CheckConstraint(
            "consecutive_failed_checks >= 0",
            name="ck_organization_email_domains_failed_checks_nonneg",
        ),
    )

    @property
    def is_operational(self) -> bool:
        """True when the send cascade should consider this domain.

        ``verified`` is the only status where outbound goes out with
        the org's own from-address; ``pending`` / ``demoted`` /
        ``released`` all fall through to platform-from.
        """
        return self.verification_status == VERIFICATION_STATUS_VERIFIED


__all__ = [
    "EmailSenderDomain",
    "OrganizationEmailDomain",
    "VERIFICATION_STATUS_PENDING",
    "VERIFICATION_STATUS_VERIFIED",
    "VERIFICATION_STATUS_DEMOTED",
    "VERIFICATION_STATUS_RELEASED",
]
