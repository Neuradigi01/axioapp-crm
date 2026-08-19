"""AI Assistants module — SQLAlchemy 2.x async models.

Five tenant-scoped, RLS-on tables. The ENUMs are created by
migration ``0201_ai_assistants_schema``; the model declarations
reference them with ``create_type=False`` so ``Base.metadata.create_all``
(used in tests before Alembic runs) doesn't try to CREATE TYPE
twice.

See :mod:`core.ai_assistants.__init__` for the conceptual map.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.shared.db import Base
from src.app.shared.orm import TenantScoped

# --- ENUMs ----------------------------------------------------------------


class AiAssistantStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


ai_assistant_status_enum = ENUM(
    AiAssistantStatus,
    name="ai_assistant_status",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class KnowledgeSourceType(str, enum.Enum):
    file = "file"
    text = "text"
    url = "url"


knowledge_source_type_enum = ENUM(
    KnowledgeSourceType,
    name="knowledge_source_type",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class KnowledgeStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed_no_text = "failed_no_text"
    failed_stuck = "failed_stuck"
    failed_ingest = "failed_ingest"
    pending_delete = "pending_delete"
    pending_cancel = "pending_cancel"


knowledge_status_enum = ENUM(
    KnowledgeStatus,
    name="knowledge_status",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class ChunkStatus(str, enum.Enum):
    ready = "ready"
    pending_delete = "pending_delete"


chunk_status_enum = ENUM(
    ChunkStatus,
    name="chunk_status",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class CostStatus(str, enum.Enum):
    pending_llm_confirm = "pending_llm_confirm"
    confirmed = "confirmed"
    reconciled = "reconciled"
    failed = "failed"


cost_status_enum = ENUM(
    CostStatus,
    name="cost_status",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


class LeadCaptureMode(str, enum.Enum):
    """Step 16 — how (and whether) the runtime captures leads from
    an anonymous visitor mid-conversation.

    * ``off`` — no capture. Historical default; conversation stays
      anonymous unless the operator manually links it.
    * ``detect_email`` — every user message is regex-scanned for an
      email; on match, upsert a lead + attach it to the conversation.
    * ``ask_at_turn`` — at conversation turn N the runtime injects
      a system-side prompt asking for the visitor's email; the model
      weaves the ask into its reply. On the visitor's next message
      the runtime scans for an email (same as ``detect_email``).
    """

    off = "off"
    detect_email = "detect_email"
    ask_at_turn = "ask_at_turn"


lead_capture_mode_enum = ENUM(
    LeadCaptureMode,
    name="ai_assistant_lead_capture_mode",
    create_type=False,
    values_callable=lambda cls: [e.value for e in cls],
)


# --- Models ---------------------------------------------------------------


class AiAssistant(Base, TenantScoped):
    """One row per stored AI assistant.

    Optimistic concurrency via ``version_id_col`` on ``version``:
    every UPDATE checks the version in the WHERE clause + increments
    it; a mismatched version raises SQLAlchemy's ``StaleDataError``
    which the service layer translates to HTTP 409 (Step 6).
    """

    __tablename__ = "tbl_ai_assistants"
    __table_args__ = (
        Index(
            "ix_ai_assistants_org_status",
            "org_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AiAssistantStatus] = mapped_column(
        ai_assistant_status_enum,
        nullable=False,
        server_default=sql_text("'draft'"),
    )
    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_ai_provider_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        server_default=sql_text("0.5"),
    )
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=sql_text("'{}'::text[]"),
    )
    retry_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    fallback_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=sql_text("'I''m sorry, I can''t help with that right now.'"),
    )
    allowed_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=sql_text("'{}'::text[]"),
    )
    output_sanitizer_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sql_text("true"),
    )
    budget_cap_override_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    # Optimistic-concurrency version. Referenced by ``__mapper_args__``
    # below via ``version_id_col`` — SQLAlchemy's default
    # ``version_id_generator`` (integer increment) auto-bumps on every
    # UPDATE and adds ``AND version = :current`` to the WHERE clause;
    # a stale caller raises StaleDataError which the service
    # translates to HTTP 409. ``server_default=1`` covers INSERT.
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("1"),
    )

    # Declared here — inside the class body — so SQLAlchemy's mapper
    # constructor picks up the version_id_col reference at
    # class-definition time. Reassigning __mapper_args__ AFTER the
    # class body is a no-op (the mapper is already built).
    __mapper_args__ = {"version_id_col": version}  # type: ignore[dict-item]
    # Plain UUID (no FK) — matches the workflows/chatbots convention.
    # The users table is `users` (legacy, pre-rename); avoiding a
    # hard FK keeps this module decoupled from the rename timeline.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    interface_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    styling_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    # Step 16 — auto-lead-capture config. Nullable / defaulted so
    # every pre-Step-16 assistant survives the ALTER without a
    # backfill. Runtime enforces ``mode`` semantics; the columns
    # are otherwise dumb config.
    lead_capture_mode: Mapped[LeadCaptureMode] = mapped_column(
        lead_capture_mode_enum,
        nullable=False,
        server_default=sql_text("'off'"),
    )
    lead_capture_turn_n: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("3"),
    )
    lead_capture_message: Mapped[str | None] = mapped_column(
        Text,
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


class AiAssistantKnowledge(Base, TenantScoped):
    """One row per uploaded / typed / URL-crawled knowledge source.

    Content-hash dedup uses the unique constraint on ``(assistant_id,
    content_hash)`` — re-uploading the same file returns the existing
    row rather than creating a duplicate (Step 10 handles the return
    shape).
    """

    __tablename__ = "tbl_ai_assistant_knowledge"
    __table_args__ = (
        UniqueConstraint(
            "assistant_id",
            "content_hash",
            name="uq_ai_assistant_knowledge_assistant_hash",
        ),
        Index(
            "ix_ai_assistant_knowledge_assistant_status",
            "assistant_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_ai_assistants.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        knowledge_source_type_enum,
        nullable=False,
    )
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[KnowledgeStatus] = mapped_column(
        knowledge_status_enum,
        nullable=False,
        server_default=sql_text("'pending'"),
    )
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
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


class AiAssistantChunk(Base, TenantScoped):
    """One row per embedded chunk. The ``embedding`` column is a
    pgvector ``VECTOR(1536)`` — sized for OpenAI's
    ``text-embedding-3-small``. Step 4's HNSW index + composite
    ``(org_id, status)`` b-tree back the top-K retrieval query.
    """

    __tablename__ = "tbl_ai_assistant_chunks"
    __table_args__ = (
        Index(
            "ix_ai_assistant_chunks_org_status",
            "org_id",
            "status",
        ),
        Index(
            "ix_ai_assistant_chunks_knowledge",
            "knowledge_id",
        ),
        UniqueConstraint(
            "knowledge_id",
            "chunk_index",
            name="uq_ai_assistant_chunks_knowledge_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_ai_assistant_knowledge.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ChunkStatus] = mapped_column(
        chunk_status_enum,
        nullable=False,
        server_default=sql_text("'ready'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("now()"),
    )


class AiAssistantMessageMeta(Base, TenantScoped):
    """AI-specific side-table on :class:`~core.conversations.models.Message`.

    Keyed on ``message_id`` (PK + FK CASCADE). ``assistant_id`` is
    ``SET NULL`` on assistant delete so historical cost + audit
    records survive the assistant being removed (the operator can
    still see "this conversation cost $X even though the assistant
    is now gone").
    """

    __tablename__ = "tbl_ai_assistant_message_meta"
    __table_args__ = (
        Index(
            "ix_ai_assistant_message_meta_org_assistant_created",
            "org_id",
            "assistant_id",
            "created_at",
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_ai_assistants.id", ondelete="SET NULL"),
        nullable=True,
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sql_text("0"),
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default=sql_text("0"),
    )
    cost_status: Mapped[CostStatus] = mapped_column(
        cost_status_enum,
        nullable=False,
        server_default=sql_text("'pending_llm_confirm'"),
    )
    provider_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=sql_text("'{}'::uuid[]"),
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


class AiAssistantInstructionAudit(Base, TenantScoped):
    """Append-only audit log for changes to the assistant's prompt,
    model, temperature, and other high-signal fields. Written from
    Step 8's tab-save flow so an insider inserting a URL-exfiltration
    prompt shows up here with a diff."""

    __tablename__ = "tbl_ai_assistant_instruction_audit"
    __table_args__ = (
        Index(
            "ix_ai_assistant_instruction_audit_assistant_changed",
            "assistant_id",
            "changed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    assistant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tbl_ai_assistants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Plain UUID (no FK) — same rationale as
    # AiAssistant.created_by_user_id above.
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = [
    "AiAssistant",
    "AiAssistantChunk",
    "AiAssistantInstructionAudit",
    "AiAssistantKnowledge",
    "AiAssistantMessageMeta",
    "AiAssistantStatus",
    "ChunkStatus",
    "CostStatus",
    "KnowledgeSourceType",
    "KnowledgeStatus",
    "LeadCaptureMode",
    "ai_assistant_status_enum",
    "chunk_status_enum",
    "cost_status_enum",
    "knowledge_source_type_enum",
    "knowledge_status_enum",
    "lead_capture_mode_enum",
]
