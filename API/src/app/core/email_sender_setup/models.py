"""ORM for the email sender-setup module.

One table: ``tbl_email_sender_domains``. Tenant-scoped via the shared
``TenantScoped`` mixin so the ``org_isolation`` RLS policy applies +
the ``do_orm_execute`` listener injects the ``org_id`` filter on every
read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
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


__all__ = ["EmailSenderDomain"]
