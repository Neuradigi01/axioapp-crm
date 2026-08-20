"""Pydantic v2 request + response shapes for the AI Assistants
module.

Write schemas set ``extra='forbid'`` and explicitly whitelist
inputs — attempts to POST ``{"org_id": "<victim>", "id": "<forged>",
"version": 99, ...}`` return 422 at the schema layer before the
service ever sees them (mass-assignment defence, Attacker review
H2).

Read schemas expose only what an operator UI needs. The audit
table (``tbl_ai_assistant_instruction_audit``) has its own read
endpoints in a future step; it's never inlined here to keep the
list-view payload cheap.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.ai_assistants.models import (
    AiAssistantStatus,
    KnowledgeSourceType,
    KnowledgeStatus,
    LeadCaptureMode,
)

# --- Bounded field constraints -------------------------------------------
# Sourced from the migration; keep in sync with the DB CHECKs.
_NAME_MIN = 1
_NAME_MAX = 200
_DESC_MAX = 4000
_MODEL_MAX = 120
_TEMPERATURE_MIN = Decimal("0.0")
_TEMPERATURE_MAX = Decimal("2.0")
_INSTRUCTIONS_MAX = 20_000
_STOP_KEYWORDS_MAX_ITEMS = 32
_STOP_KEYWORD_MAX_LEN = 64
_ALLOWED_DOMAINS_MAX_ITEMS = 64
_ALLOWED_DOMAIN_MAX_LEN = 253  # RFC 1035 hostname cap
_FALLBACK_MSG_MAX = 2000
_RETRY_ATTEMPTS_MAX = 5
_BUDGET_MAX = Decimal("9999.9999")
_RETENTION_DAYS_MIN = 1
_RETENTION_DAYS_MAX = 400  # Hard cap; org default 90


# --- Create ---------------------------------------------------------------


class AiAssistantCreate(BaseModel):
    """Operator POSTs this to create a new assistant.

    ``key_id`` must belong to the caller's org — the service
    validates this and 404s (not 403) on mismatch to avoid leaking
    the existence of another org's key.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=_NAME_MIN, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    key_id: uuid.UUID
    model: str = Field(..., min_length=1, max_length=_MODEL_MAX)
    temperature: Decimal = Field(
        default=Decimal("0.5"),
        ge=_TEMPERATURE_MIN,
        le=_TEMPERATURE_MAX,
    )
    instructions: str | None = Field(default=None, max_length=_INSTRUCTIONS_MAX)
    stop_keywords: list[str] = Field(
        default_factory=list,
        max_length=_STOP_KEYWORDS_MAX_ITEMS,
    )
    retry_attempts: int = Field(default=0, ge=0, le=_RETRY_ATTEMPTS_MAX)
    fallback_message: str | None = Field(default=None, max_length=_FALLBACK_MSG_MAX)
    allowed_domains: list[str] = Field(
        default_factory=list,
        max_length=_ALLOWED_DOMAINS_MAX_ITEMS,
    )
    output_sanitizer_enabled: bool = True
    budget_cap_override_usd: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=_BUDGET_MAX,
    )
    lead_capture_mode: LeadCaptureMode = LeadCaptureMode.off
    lead_capture_turn_n: int = Field(default=3, ge=1, le=20)
    lead_capture_message: str | None = Field(default=None, max_length=500)
    retention_days: int | None = Field(
        default=None,
        ge=_RETENTION_DAYS_MIN,
        le=_RETENTION_DAYS_MAX,
    )


# --- Update ---------------------------------------------------------------


class AiAssistantUpdate(BaseModel):
    """Partial update. Every field optional except ``version`` which
    is REQUIRED — the service compares against the DB row for
    optimistic-concurrency control and 409s on mismatch."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=_NAME_MIN, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESC_MAX)
    key_id: uuid.UUID | None = None
    model: str | None = Field(default=None, min_length=1, max_length=_MODEL_MAX)
    temperature: Decimal | None = Field(
        default=None,
        ge=_TEMPERATURE_MIN,
        le=_TEMPERATURE_MAX,
    )
    instructions: str | None = Field(default=None, max_length=_INSTRUCTIONS_MAX)
    stop_keywords: list[str] | None = Field(
        default=None,
        max_length=_STOP_KEYWORDS_MAX_ITEMS,
    )
    retry_attempts: int | None = Field(default=None, ge=0, le=_RETRY_ATTEMPTS_MAX)
    fallback_message: str | None = Field(default=None, max_length=_FALLBACK_MSG_MAX)
    allowed_domains: list[str] | None = Field(
        default=None,
        max_length=_ALLOWED_DOMAINS_MAX_ITEMS,
    )
    output_sanitizer_enabled: bool | None = None
    budget_cap_override_usd: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=_BUDGET_MAX,
    )
    lead_capture_mode: LeadCaptureMode | None = None
    lead_capture_turn_n: int | None = Field(default=None, ge=1, le=20)
    lead_capture_message: str | None = Field(default=None, max_length=500)
    retention_days: int | None = Field(
        default=None,
        ge=_RETENTION_DAYS_MIN,
        le=_RETENTION_DAYS_MAX,
    )
    # JSONB blobs owned by the Assistant Interface + Styling tabs. Sent
    # as full replacement (frontend holds the merged copy in its signal
    # store, patches keys as the operator edits, then ships the whole
    # object on Save). ``dict[str, Any]`` intentionally permissive — the
    # widget renderer defends against unknown keys, and locking a rigid
    # shape here would force a schema bump every time the UI adds a new
    # colour or text slot.
    interface_config: dict[str, Any] | None = None
    styling_config: dict[str, Any] | None = None


# --- Read -----------------------------------------------------------------


class AiAssistantRead(BaseModel):
    """Full assistant. Excludes the audit rows (fetched separately)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    status: AiAssistantStatus
    key_id: uuid.UUID
    model: str
    temperature: Decimal
    instructions: str | None
    stop_keywords: list[str]
    retry_attempts: int
    fallback_message: str
    allowed_domains: list[str]
    output_sanitizer_enabled: bool
    budget_cap_override_usd: Decimal | None
    lead_capture_mode: LeadCaptureMode
    lead_capture_turn_n: int
    lead_capture_message: str | None
    retention_days: int | None
    version: int
    created_by_user_id: uuid.UUID | None
    interface_config: dict[str, Any]
    styling_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AiAssistantListItem(BaseModel):
    """Trimmed shape for the list view. No prompts / configs to keep
    the payload small when an org has many assistants."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: AiAssistantStatus
    model: str
    key_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    version: int


# --- Knowledge (Step 10) --------------------------------------------------

# Bounds sourced from the same file_upload / ingest constants — keep
# in sync with :mod:`~core.ai_assistants.file_upload` +
# :mod:`~core.ai_assistants.ingest`.
_KNOWLEDGE_TITLE_MAX = 500  # matches original_filename column length
_KNOWLEDGE_BODY_MAX = 20 * 1024 * 1024  # 20 MB decoded-text cap
_KNOWLEDGE_URL_MAX = 4096


class KnowledgeCreateText(BaseModel):
    """Operator POSTs a typed-in knowledge blob."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=_KNOWLEDGE_TITLE_MAX)
    body_text: str = Field(..., min_length=1, max_length=_KNOWLEDGE_BODY_MAX)


class KnowledgeCreateUrl(BaseModel):
    """Operator pastes a URL to ingest. SSRF checks fire at the
    service layer (before the row is inserted), so a private-IP URL
    gets a 422 without leaving a half-baked row behind."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=_KNOWLEDGE_TITLE_MAX)
    url: str = Field(..., min_length=1, max_length=_KNOWLEDGE_URL_MAX)


class KnowledgeRead(BaseModel):
    """Full knowledge row as surfaced on the list + poll endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assistant_id: uuid.UUID
    source_type: KnowledgeSourceType
    original_filename: str | None
    url: str | None
    mime_type: str | None
    size_bytes: int | None
    status: KnowledgeStatus
    status_message: str | None
    progress_pct: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeCreateResponse(BaseModel):
    """Wraps :class:`KnowledgeRead` with a ``duplicate`` flag so the
    operator UI can render "we already had this file" vs "started
    fresh ingest" without a second call."""

    model_config = ConfigDict(from_attributes=True)

    duplicate: bool
    knowledge: KnowledgeRead


# --- Analytics (Step 16) --------------------------------------------------


class TopQuestionRow(BaseModel):
    """One entry in the "top questions" list. ``normalized`` is
    ``LOWER(TRIM(text))`` so "Hi" and "hi " collapse together."""

    model_config = ConfigDict(from_attributes=True)

    normalized: str
    count: int


class AiAssistantAnalytics(BaseModel):
    """Payload for ``GET /ai-assistants/{id}/analytics``. Trimmed to
    the fields the Analytics page renders today; ROI-style rollups
    (bounce rate, human takeover count) are follow-up work."""

    model_config = ConfigDict(from_attributes=True)

    window_days: int
    message_count: int
    total_cost_usd: Decimal
    top_questions: list[TopQuestionRow]


__all__ = [
    "AiAssistantAnalytics",
    "AiAssistantCreate",
    "AiAssistantListItem",
    "AiAssistantRead",
    "AiAssistantUpdate",
    "KnowledgeCreateResponse",
    "KnowledgeCreateText",
    "KnowledgeCreateUrl",
    "KnowledgeRead",
    "TopQuestionRow",
]
