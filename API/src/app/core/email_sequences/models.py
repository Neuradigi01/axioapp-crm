"""Email-sequences ORM models.

Four tables:

  * `email_sequences`        — static definition: name + active flag.
  * `email_sequence_steps`   — ordered (step_order) (delay_days,
                               template_id) tuples for a sequence.
  * `email_sequence_enrollments`
                             — one row per (sequence, contact); carries
                               the state machine and current step.
  * `email_sequence_enrollment_steps`
                             — per-step instance: scheduled_at / sent_at
                               / skip flags / outbound `messages.id`.

Soft delete on `email_sequences` via `deleted_at` — historical
enrollments survive a sequence delete (state freezes; scheduler
respects `deleted_at IS NULL` filter on enrollment processing).

State machine for `EnrollmentState`:

  active ─┬─→ completed
          ├─→ paused_on_reply  (auto, on inbound email reply)
          ├─→ paused_manual    (operator pause)
          └─→ cancelled        (operator cancel; one-way)

`paused_*` → resume → `active` (operator resume).
`cancelled` is terminal — no resume.

Tenant-scoped via `TenantScoped` mixin + RLS policy from migrations
0084 + 0085.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class EnrollmentState(str, enum.Enum):
    """Lifecycle states for an enrollment row.

    Stored as plain TEXT on the row with a CHECK constraint (see
    migration 0085) so future state additions don't require a Postgres
    enum migration — only a CHECK rewrite.
    """

    active = "active"
    completed = "completed"
    paused_on_reply = "paused_on_reply"
    paused_manual = "paused_manual"
    cancelled = "cancelled"


class EmailSequence(Base, TenantScoped):
    __tablename__ = "tbl_email_sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class EmailSequenceStep(Base, TenantScoped):
    __tablename__ = "tbl_email_sequence_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class EmailSequenceEnrollment(Base, TenantScoped):
    __tablename__ = "tbl_email_sequence_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    enrolled_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # Stored as TEXT with a DB CHECK constraint (migration 0085) — not
    # a Postgres ENUM, so adding a state in v2 doesn't need an enum-
    # alter migration.
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    current_step_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            EnrollmentState.completed.value,
            EnrollmentState.cancelled.value,
        }

    @property
    def is_paused(self) -> bool:
        return self.state in {
            EnrollmentState.paused_on_reply.value,
            EnrollmentState.paused_manual.value,
        }


class EmailSequenceEnrollmentStep(Base, TenantScoped):
    __tablename__ = "tbl_email_sequence_enrollment_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = [
    "EmailSequence",
    "EmailSequenceEnrollment",
    "EmailSequenceEnrollmentStep",
    "EmailSequenceStep",
    "EnrollmentState",
]
