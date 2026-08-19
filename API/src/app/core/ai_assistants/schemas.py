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

from src.app.core.ai_assistants.models import AiAssistantStatus

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


__all__ = [
    "AiAssistantCreate",
    "AiAssistantListItem",
    "AiAssistantRead",
    "AiAssistantUpdate",
]
