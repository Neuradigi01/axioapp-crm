"""Chatbots module — SQLAlchemy 2.x async models.

Five tenant-scoped, RLS-on tables back the Pabbly-Chatflow-style
inbound-message bot runtime. The matching ENUMs are created by
migration ``0189_chatbots_init``; model declarations reference them
with ``create_type=False`` so SQLAlchemy doesn't try to CREATE TYPE
on test-DB metadata create.

See :mod:`core.chatbots.__init__` for the conceptual map and
``tasks/chatbot-builder/README.md`` for the full track plan.
"""

from __future__ import annotations

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
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.chatbots.enums import (
    chatbot_run_status_enum,
    chatbot_status_enum,
    chatbot_step_status_enum,
    trigger_channel_enum,
    trigger_mode_enum,
)
from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped


class Chatbot(Base, TenantScoped):
    """Bot definition.

    ``trigger_config`` JSONB carries the whole trigger editor payload
    (channel, mode, keywords, regex_pattern, case_sensitive,
    first_message_only). ``graph`` JSONB carries ``{nodes: [...],
    edges: [...]}``. ``priority`` breaks ties when two live bots match
    the same message (Decision §13). ``version_number`` is bumped by
    the service on each save and enforces optimistic locking
    (Case #27).
    """

    __tablename__ = "tbl_chatbots"
    __table_args__ = (
        Index("ix_chatbots_org_status", "org_id", "status"),
        Index("ix_chatbots_org_priority_created", "org_id", "priority", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=sql_text("'Custom'"),
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        chatbot_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("100"),
    )
    trigger_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text(
            "'{\"channel\": \"any\", \"mode\": \"any\", \"keywords\": [], "
            "\"regex_pattern\": null, \"case_sensitive\": false, "
            "\"first_message_only\": false}'::jsonb"
        ),
    )
    graph: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{\"nodes\": [], \"edges\": []}'::jsonb"),
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("1"),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
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
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ChatbotRun(Base, TenantScoped):
    """One enrolment of a bot on a conversation.

    FK to ``chatbot`` is RESTRICT so hard-delete requires runs to be
    cleaned first (soft-archive is the normal path). Conversation +
    contact + lead FKs SET NULL so the run survives merges/deletes and
    the diagnostics UI can still show what happened. ``context`` JSONB
    holds the running state — conversation_id, contact_id, prior
    answers, api-request captures.
    """

    __tablename__ = "tbl_chatbot_runs"
    __table_args__ = (
        Index(
            "ix_chatbot_runs_bot_conv_status",
            "org_id",
            "chatbot_id",
            "conversation_id",
            "status",
        ),
        Index(
            "ix_chatbot_runs_conv_parked",
            "conversation_id",
            "status",
            postgresql_where=sql_text("status = 'parked'"),
        ),
        Index(
            "ix_chatbot_runs_org_started",
            "org_id",
            sql_text("started_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    chatbot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        chatbot_run_status_enum,
        nullable=False,
        server_default=sql_text("'running'"),
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    current_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_test: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("false"),
    )
    canceled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ChatbotStepRun(Base, TenantScoped):
    """Per-node audit log; feeds the diagnostics UI in a follow-up
    track. One row per node the engine touched; CASCADE with the
    parent run so cleanup is trivial."""

    __tablename__ = "tbl_chatbot_step_runs"
    __table_args__ = (
        Index(
            "ix_chatbot_step_runs_run_started",
            "run_id",
            sql_text("started_at"),
        ),
        Index(
            "ix_chatbot_step_runs_org_errored",
            "org_id",
            sql_text("started_at DESC"),
            postgresql_where=sql_text("status = 'errored'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbot_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        chatbot_step_status_enum,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    output: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    output_edge_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ChatbotMeter(Base, TenantScoped):
    """Reply counters for the runaway guard (Decision §9).

    Two row shapes coexist in this table:

    - Per-conversation-per-bot: ``bot_id`` + ``conversation_id`` both
      set. Cap: 50 replies / 24h (configurable per bot).
    - Per-org global: both ``bot_id`` and ``conversation_id`` NULL.
      Cap: 10,000 replies / 24h.

    Uniqueness is enforced by two partial indexes below so both shapes
    can coexist without ``NULLS NOT DISTINCT`` gymnastics.
    ``window_start`` is refreshed lazily on the next increment when
    ``now > window_start + 24h``. The atomic increment SQL is in
    ``core/chatbots/data_access.py`` (Step 6).
    """

    __tablename__ = "tbl_chatbot_meters"
    __table_args__ = (
        # Per-bot-per-conversation uniqueness.
        Index(
            "uq_chatbot_meters_bot_conv",
            "org_id",
            "bot_id",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text(
                "bot_id IS NOT NULL AND conversation_id IS NOT NULL"
            ),
        ),
        # Exactly one per-org global row.
        Index(
            "uq_chatbot_meters_org_global",
            "org_id",
            unique=True,
            postgresql_where=sql_text(
                "bot_id IS NULL AND conversation_id IS NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class ChatbotPendingReply(Base, TenantScoped):
    """Signed-email-reply-URL nonce store (Step 11).

    One row per generated URL. The GET interstitial verifies the
    signature + expiry + not-yet-consumed; the POST atomically flips
    ``consumed_at`` and records the customer's "click" as an inbound
    message on the linked conversation. Rows past ``expires_at`` are
    swept nightly.
    """

    __tablename__ = "tbl_chatbot_pending_replies"
    __table_args__ = (
        UniqueConstraint("nonce", name="uq_chatbot_pending_replies_nonce"),
        Index("ix_chatbot_pending_replies_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbot_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    button_id: Mapped[str] = mapped_column(String(128), nullable=False)
    button_label: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_contacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )

    # Named channel_used so a future rotation of signing keys can log
    # which channel the URL was originally minted for. String, not
    # ENUM — this row is write-once and never joined against enum
    # columns.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)


class ChatbotTriggerDiagnostic(Base, TenantScoped):
    """One row per matcher decision the operator would want to
    inspect (``tasks/chatbot-builder`` Step 5, migration 0192).

    Fed by :mod:`core.chatbots.trigger_matcher` on every inbound
    message that reaches the matcher; the diagnostics UI (follow-up
    track) reads from here to answer "why did / didn't my bot fire".
    Nightly sweeper TTLs rows > 90 days.

    ``reason`` is a short slug — ``skipped_by_priority``,
    ``opted_out``, ``active_run_exists``, ``no_match``,
    ``regex_error``, ``matched_and_dispatched``. String not enum so
    new reasons don't require a migration.
    """

    __tablename__ = "tbl_chatbot_trigger_diagnostics"
    __table_args__ = (
        Index(
            "ix_chatbot_trigger_diag_org_created",
            "org_id",
            sql_text("created_at DESC"),
        ),
        Index(
            "ix_chatbot_trigger_diag_conv",
            "conversation_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class ChatbotVersion(Base, TenantScoped):
    """Append-only version history for a bot definition
    (``tasks/chatbot-builder`` Step 2, migration 0190).

    Every ``save_chatbot_service`` writes a row here BEFORE bumping
    ``tbl_chatbots.version_number``. Version number matches
    ``tbl_chatbots.version_number`` at the moment of that save, so
    rollback reads ``WHERE chatbot_id=? AND version_number=?`` and
    restores the JSONB blobs verbatim. UniqueConstraint on
    ``(chatbot_id, version_number)`` blocks concurrent double-saves
    from colliding on the same slot.
    """

    __tablename__ = "tbl_chatbot_versions"
    __table_args__ = (
        UniqueConstraint(
            "chatbot_id",
            "version_number",
            name="uq_chatbot_versions_bot_version",
        ),
        Index(
            "ix_chatbot_versions_bot_created",
            "chatbot_id",
            sql_text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    chatbot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_chatbots.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trigger_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )
