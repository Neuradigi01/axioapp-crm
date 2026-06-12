"""Call-center models.

Three tables:

- `CallOutcome` — config table per tenant. Defaults are seeded by
  `seed_call_outcomes` (5 generic outcomes: connected / no_answer /
  busy / voicemail / wrong_number). The furniture pack adds its own in
  Phase 4.2 — never hardcoded in core (rule 7).
- `Call` — one row per phone call. `contact_id` is nullable so an
  inbound from an unknown number still records. `outcome_id` is
  nullable until the agent picks one. `custom_data` JSONB carries
  whatever the org defined in `custom_field_definitions` for
  `entity_type='call'`.
- `CallTranscript` — separate table because transcripts can be long
  and we usually fetch them on-demand, not in the list view.

Tenant-scoped, RLS-on. Migration 0019 adds the indexes for hot reads
(by org+started_at desc for the list, by contact_id for "calls for
this contact", by outcome_id for analytics group-bys).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class CallDirection(str, enum.Enum):
    in_ = "in"
    out = "out"


call_direction_enum = ENUM(
    CallDirection,
    name="call_direction",
    values_callable=lambda obj: [m.value for m in obj],
)


class CallOutcome(Base, TenantScoped):
    __tablename__ = "tbl_call_outcomes"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_call_outcomes_org_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=sql_text("'#6b7280'")
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class Call(Base, TenantScoped):
    __tablename__ = "tbl_calls"
    __table_args__ = (
        Index("ix_calls_org_started_at", "org_id", "started_at"),
        Index("ix_calls_contact_id", "contact_id"),
        Index("ix_calls_outcome_id", "outcome_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    direction: Mapped[CallDirection] = mapped_column(
        call_direction_enum, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_call_outcomes.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    custom_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class CallTranscript(Base, TenantScoped):
    __tablename__ = "tbl_call_transcripts"
    __table_args__ = (
        Index("ix_call_transcripts_call_id", "call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_calls.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
