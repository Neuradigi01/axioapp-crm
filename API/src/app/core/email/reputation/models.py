"""ORM for ``tbl_organization_email_reputation``.

One row per (org × envelope). ``platform_from`` gets a single row per
org (``domain_id`` NULL). ``own_domain`` gets one row per
(org, domain_id) so a shed on one own-domain doesn't take down the
others. Enforced by two partial unique indexes in migration
0235_email_reputation — see the migration file's docstring.

Redis 24h counters are the source of truth for ``bounce_count_24h``
etc. — the columns on this table are convenience mirrors written by
the events-webhook path so a read-only dashboard doesn't need to talk
to Redis. On disagreement, Redis wins (the counters module reads
buckets directly).

Fields the send-gate reads on every dispatch:

  * ``warmup_stage`` — indexed into the config's ladder for the cap.
  * ``daily_sent_count`` — vs cap, gates the send.
  * ``reputation_state`` + ``blocked_until`` — hard reject when
    blocked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped

# Envelope-type discriminator values. Kept as module-level constants
# so callers never spell them wrong. Deliberately mirror the strings
# ``resolve_send_envelope`` (Track 2) emits — same enum, different
# storage layer, single source of truth.
ENVELOPE_TYPE_PLATFORM_FROM = "platform_from"
ENVELOPE_TYPE_OWN_DOMAIN = "own_domain"

# Reputation state machine. ``blocked`` carries the ``blocked_until``
# stamp; the hourly sweep flips ``blocked``→``ok`` once the window
# elapses.
REPUTATION_STATE_OK = "ok"
REPUTATION_STATE_WARNED = "warned"
REPUTATION_STATE_BLOCKED = "blocked"


class OrganizationEmailReputation(Base, TenantScoped):
    """Per-(org, envelope) reputation state.

    Single row per org for ``platform_from``, one row per verified
    own-domain for ``own_domain``. Two partial unique indexes in the
    migration enforce the split (see 0235_email_reputation.py).
    """

    __tablename__ = "tbl_organization_email_reputation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    # Override TenantScoped's RESTRICT with CASCADE so hard-deleting
    # an org tears down its reputation rows cleanly. Mirrors the
    # OrganizationEmailDomain pattern from Track 2.
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    envelope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # NULL for ``platform_from``; FK to the verified own-domain for
    # ``own_domain``. Partial unique indexes in the migration ensure
    # the shape.
    domain_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_organization_email_domains.id", ondelete="CASCADE"),
        nullable=True,
    )

    warmup_stage: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    warmup_stage_earned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warmup_stage_current_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )

    daily_sent_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    daily_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Convenience mirrors of the Redis 24h counters — the events-
    # webhook path writes both. Dashboard reads these; the evaluators
    # (Step 4) prefer Redis so a rollup-lag doesn't shift the
    # threshold verdict.
    bounce_count_24h: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    complaint_count_24h: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    delivered_count_24h: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )

    reputation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=sql_text("'ok'")
    )
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
        onupdate=sql_text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "envelope_type IN ('platform_from', 'own_domain')",
            name="ck_email_reputation_envelope_enum",
        ),
        CheckConstraint(
            "reputation_state IN ('ok', 'warned', 'blocked')",
            name="ck_email_reputation_state_enum",
        ),
        CheckConstraint(
            "(envelope_type = 'platform_from' AND domain_id IS NULL) "
            "OR (envelope_type = 'own_domain' AND domain_id IS NOT NULL)",
            name="ck_email_reputation_envelope_domain_shape",
        ),
        CheckConstraint(
            "warmup_stage >= 0",
            name="ck_email_reputation_warmup_stage_nonneg",
        ),
        Index(
            "ix_email_reputation_org_envelope",
            "org_id",
            "envelope_type",
        ),
        Index(
            "ix_email_reputation_state_blocked_until",
            "reputation_state",
            "blocked_until",
            postgresql_where=sql_text("reputation_state = 'blocked'"),
        ),
        Index(
            "uq_email_reputation_platform_from",
            "org_id",
            unique=True,
            postgresql_where=sql_text("envelope_type = 'platform_from'"),
        ),
        Index(
            "uq_email_reputation_own_domain",
            "org_id",
            "domain_id",
            unique=True,
            postgresql_where=sql_text("envelope_type = 'own_domain'"),
        ),
    )


__all__ = [
    "ENVELOPE_TYPE_OWN_DOMAIN",
    "ENVELOPE_TYPE_PLATFORM_FROM",
    "REPUTATION_STATE_BLOCKED",
    "REPUTATION_STATE_OK",
    "REPUTATION_STATE_WARNED",
    "OrganizationEmailReputation",
]
