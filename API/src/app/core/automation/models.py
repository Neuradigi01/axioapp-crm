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
    # Step 4 — idempotency key. Publisher-supplied (typically the
    # originating row's PK); the bus auto-fills a fresh UUID when
    # the publisher omits it. Unique on (trigger_id, event_id) via
    # the partial index `uq_automation_runs_trigger_event_id` from
    # migration 0128.
    event_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sql_text("gen_random_uuid()::text"),
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
    # Step 14 — engagement tracking. First open + first click only;
    # multi-event tracking deferred (the timestamps stay on the run
    # row for fast contact-timeline reads). Populated by the
    # ``/api/v1/automations/track/open/{token}`` (pixel beacon) and
    # ``/api/v1/automations/track/click/{token}`` (redirect) public
    # endpoints — both HMAC-signed on the run id to prevent guessing.
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    clicked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SuppressionReason(str, enum.Enum):
    """Why a recipient was added to the suppression list.

    ``hard_bounce`` — provider returned 5xx (invalid mailbox).
    ``complaint``   — provider received a spam complaint
                     (Mailgun ``complained``, SendGrid ``spamreport``,
                     SES ``Complaint``, Postmark ``SpamComplaint``).
    ``unsubscribe`` — provider's unsubscribe webhook + the
                     CRM's own one-click unsubscribe header click.
    ``manual``      — operator added via the Settings → Email
                     suppression list UI.
    """

    hard_bounce = "hard_bounce"
    complaint = "complaint"
    unsubscribe = "unsubscribe"
    manual = "manual"


suppression_reason_enum = ENUM(
    SuppressionReason,
    name="automation_suppression_reason",
    values_callable=lambda obj: [m.value for m in obj],
)


class AutomationSuppression(Base, TenantScoped):
    """One row per (org, channel, address) pair the send-guard must
    refuse. Populated by the bounce-handler webhooks (hard-bounce /
    complaint / unsubscribe) + the Settings → Email "Add to
    suppression list" manual action.

    The unique ``(org_id, channel, address)`` constraint means a
    contact who hits multiple suppression reasons keeps the FIRST
    entry (e.g. complaint > unsubscribe — the complaint stays on
    record). Operators "rehabilitate" an address via DELETE on the
    row, not by inserting a fresh one."""

    __tablename__ = "tbl_automation_suppressions"
    __table_args__ = (
        Index(
            "uq_automation_suppressions_org_channel_address",
            "org_id",
            "channel",
            "address",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        conversation_channel_enum, nullable=False
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[SuppressionReason] = mapped_column(
        suppression_reason_enum, nullable=False
    )
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class EmailBounceEvent(Base, TenantScoped):
    """Append-only audit log of every bounce / complaint /
    unsubscribe webhook the CRM has received from any provider.

    ``provider_event_id`` is unique across the whole table so that
    a provider re-delivery of the same webhook doesn't create a
    duplicate row. The raw provider payload is preserved verbatim
    on ``raw_payload`` so operators have a paper trail for any
    suppression decision.

    Lives in the automation models module rather than core/email/
    because the suppression write — the side effect of the bounce —
    is automation-engine state. Email module's bounce_handler
    parses the provider payload, normalises it, and calls into the
    automation DAL to write the row + the suppression."""

    __tablename__ = "tbl_email_bounce_events"
    __table_args__ = (
        Index(
            "ix_email_bounce_events_org_address",
            "org_id",
            "email_address",
        ),
        Index(
            "uq_email_bounce_events_provider_event_id",
            "provider_event_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    email_address: Mapped[str] = mapped_column(Text, nullable=False)
    # 'hard', 'soft', 'complaint', 'unsubscribe'. Stored as text
    # (not enum) so a future provider's specific bounce sub-type
    # ('spamtrap', 'block', ...) lands without an ALTER TYPE
    # migration.
    bounce_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
