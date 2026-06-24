"""`Contact` model — Layer 1 universal CRM contact.

Stores the small set of canonical fields every furniture-CRM contact has
(name, phone, email, source, tags, notes) plus the dynamic `custom_data`
JSONB column that holds every value driven by `custom_field_definitions`
for `entity_type='contact'`. Rule 3 of the master prompt: never hardcode
furniture-specific or org-specific fields; everything beyond the core
columns goes through `custom_data`.

Tenant-scoped (RLS on, ORM filter applied). Migration 0007 layers the
search/filter indexes on top of the table:

- ``ix_contacts_org_phone``    — exact phone lookup per tenant.
- ``ix_contacts_org_email``    — exact email lookup per tenant.
- ``ix_contacts_full_name_trgm`` — GIN trigram for fuzzy `q=` search.
- ``ix_contacts_tags_gin``     — GIN on the `tags` array for tag filter.
- ``ix_contacts_custom_data_gin`` — GIN on `custom_data` for the
  `custom.<key>=value` filter style.

The WhatsApp opt-in columns (added in migration 0109,
whatsapp-platform-upgrade Step 22) are first-class for DPDP / GDPR
compliance — the campaign send guard queries them directly without
unpacking `custom_data`. This is the intentional Rule-3 override
called out in the step spec.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


# Step 22 — DPDP-ready opt-in state machine. Defined here so both
# Contact and ConsentEvent share one ENUM definition and the
# campaign send guard can import the literal set without an ORM dep.
WHATSAPP_OPT_IN_STATUSES: tuple[str, ...] = (
    "never_contacted",
    "implicit",
    "opted_in",
    "opted_out",
)
WHATSAPP_OPT_IN_SOURCES: tuple[str, ...] = (
    "form_widget",
    "bulk_import",
    "manual_entry",
    "inbound_first_message",
    "explicit_opt_in_link",
    "stop_keyword",
)

_opt_in_status_enum = ENUM(
    *WHATSAPP_OPT_IN_STATUSES,
    name="whatsapp_opt_in_status",
    create_type=False,
)
_opt_in_source_enum = ENUM(
    *WHATSAPP_OPT_IN_SOURCES,
    name="whatsapp_opt_in_source",
    create_type=False,
)


class Contact(Base, TenantScoped):
    __tablename__ = "tbl_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        server_default=text("ARRAY[]::varchar[]"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # Sales-rep owner. Mirrors `leads.assigned_to_id` / `walk_ins.
    # assigned_to_id` / `appointments.assigned_to_id`. SET NULL on
    # user delete so a contact survives the rep leaving (transfer
    # is the offboarding-flow's job — see `update-staff-offboarding/`).
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    # Denormalised "newest activity timestamp" — bumped by the
    # activities-service insert hook. Authoritative log lives in
    # the `activities` table; this is a fast-path read for the
    # list page's default sort.
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Email tracking opt-out (Step 8). Set by the public
    # `/api/v1/track/unsubscribe/{token}` endpoint and respected by
    # `send_email` (raises OptedOut) + the sequence scheduler (cancels
    # active enrollments). CAN-SPAM (US) + DPDP (IN) compliance.
    email_opt_out: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    email_opt_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # whatsapp-platform-upgrade Step 22 — DPDP opt-in state machine.
    # Status flows: never_contacted → implicit (first inbound)
    # → opted_in (explicit consent) → opted_out (STOP keyword or
    # manual override). Source records *how* the current state was
    # captured for audit + DPDP right-to-access purposes.
    whatsapp_opt_in_status: Mapped[str] = mapped_column(
        _opt_in_status_enum,
        nullable=False,
        server_default=text("'never_contacted'"),
    )
    whatsapp_opt_in_source: Mapped[str | None] = mapped_column(
        _opt_in_source_enum,
        nullable=True,
    )
    whatsapp_opt_in_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    whatsapp_opt_in_recorded_by_user_id: Mapped[uuid.UUID | None] = (
        mapped_column(UUID(as_uuid=True), nullable=True)
    )
    whatsapp_opt_out_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    whatsapp_opt_out_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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


class ConsentEvent(Base, TenantScoped):
    """Immutable append-only log of opt-in transitions
    (whatsapp-platform-upgrade Step 22).

    Every change to a contact's ``whatsapp_opt_in_status`` writes a
    row here. A PG ``BEFORE UPDATE OR DELETE`` trigger
    (``trg_consent_events_immutable``) raises an exception on any
    write that isn't an INSERT — neither ORM bugs nor stray scripts
    can rewrite history. DPDP right-to-access exports read from
    here so an auditor can see "consent was captured at X via
    Y by Z".

    ``request_evidence`` is a JSONB grab-bag for the source-specific
    proof: form-widget submissions store the submitted payload,
    STOP-keyword auto-flips store the raw inbound text, manual
    overrides record the operator's UA + reason."""

    __tablename__ = "tbl_consent_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'whatsapp'"),
    )
    old_status: Mapped[str | None] = mapped_column(
        _opt_in_status_enum,
        nullable=True,
    )
    new_status: Mapped[str] = mapped_column(
        _opt_in_status_enum,
        nullable=False,
    )
    source: Mapped[str | None] = mapped_column(
        _opt_in_source_enum,
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    request_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
