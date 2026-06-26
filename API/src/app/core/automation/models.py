"""Automation engine — SQLAlchemy 2.x async models.

Two tables back the single-event trigger engine the manager spec'd
for Module B:

* ``tbl_automation_triggers`` — one row per operator-configured
  rule. The matcher reads it ("any trigger where ``enabled = TRUE``
  and ``event_type = '<incoming event>'``"), evaluates the
  ``conditions`` JSONB against the published payload, resolves the
  recipient, and queues a Celery dispatch.

* ``tbl_automation_runs`` — append-only audit + run history. Every
  trigger firing (matched OR skipped) lands a row so the Settings
  → Automations → Run History UI (Step 9) can show ``what fired
  when + did it succeed``. ``channel_message_id`` carries the
  outbound adapter's id so a future "did the recipient open it?"
  feature can correlate inbox replies back to the run.

The ``channel`` column reuses the existing ``conversation_channel``
PG enum (declared in :mod:`core.conversations.models`); the new
``automation_run_status`` enum is created by migration
``0126_automation_schema``.

Tenant scoping via :class:`TenantScoped`. RLS policies installed in
the matching migration so the database itself blocks cross-tenant
reads even when an SQL caller forgets to filter.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.conversations.models import (
    ConversationChannel,
    conversation_channel_enum,
)
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class AutomationRunStatus(str, enum.Enum):
    """Lifecycle of a single firing.

    ``queued``     — service inserted the row; Celery hasn't picked
                     it up yet.
    ``dispatched`` — Celery worker dequeued; about to call the
                     channel adapter.
    ``sent``       — adapter returned success; ``channel_message_id``
                     populated.
    ``failed``     — adapter raised; ``error`` carries the message
                     verbatim for the run-history UI.
    ``skipped``    — pre-flight check refused the send (opt-out,
                     quiet hours, frequency cap, duplicate event
                     idempotency, …). ``error`` carries the reason.
    """

    queued = "queued"
    dispatched = "dispatched"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"


automation_run_status_enum = ENUM(
    AutomationRunStatus,
    name="automation_run_status",
    values_callable=lambda obj: [m.value for m in obj],
    create_type=False,
)


class AutomationTrigger(Base, TenantScoped):
    """One operator-configured automation rule.

    The ``conditions`` JSONB shape is documented in Step 2's
    condition evaluator (the AST the matcher walks). Step 1 only
    persists it — the matcher arrives in Step 2. ``delay_seconds``
    is the wait between event fire and send dispatch; ``0`` (the
    default) means "send immediately".

    The unique ``(org_id, lower(name))`` constraint is enforced via
    a functional unique index declared in the migration (``lower()``
    can't live in :class:`UniqueConstraint`).
    """

    __tablename__ = "tbl_automation_triggers"
    __table_args__ = (
        Index(
            "ix_automation_triggers_org_event_enabled",
            "org_id",
            "event_type",
            "enabled",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("true")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-shape predicate the matcher walks at fire time. Empty
    # dict means "always match" (the trigger fires for every event
    # of its type).
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        conversation_channel_enum, nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_message_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delay_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    # How the dispatcher resolves "who do we send to" from the
    # event payload. Step 2's resolver registry maps each string to
    # a concrete extractor (``contact.email`` → ``payload["contact"]
    # ["email"]``, etc.). ``custom`` reads ``recipient_resolver_config``
    # for a JSONB-described JSONPath.
    recipient_resolver: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sql_text("'contact.email'"),
    )
    recipient_resolver_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
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
    )


class AutomationRun(Base, TenantScoped):
    """Append-only audit of a single trigger firing.

    The dispatcher inserts the row in ``status='queued'``, flips to
    ``dispatched`` when Celery dequeues, then ``sent`` / ``failed``
    / ``skipped`` once the adapter returns. ``scheduled_at`` is the
    fire-time + ``trigger.delay_seconds``; ``dispatched_at`` /
    ``completed_at`` are stamped when the lifecycle hits those
    states.

    ``contact_id`` is best-effort — the resolver populates it when
    the recipient is a tenant contact. ``SET NULL`` on contact
    delete preserves the audit history.
    """

    __tablename__ = "tbl_automation_runs"
    __table_args__ = (
        Index(
            "ix_automation_runs_trigger_scheduled_desc",
            "trigger_id",
            sql_text("scheduled_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    trigger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_automation_triggers.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[AutomationRunStatus] = mapped_column(
        automation_run_status_enum,
        nullable=False,
        server_default=sql_text("'queued'"),
    )
    channel_message_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
