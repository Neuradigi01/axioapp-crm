"""Pydantic v2 schemas for the WhatsApp account connect surface.

`WhatsAppConnectIn` is the HTTP body for `POST /connect`. The operator
pastes the five Meta-provided values + chooses a verify_token (any
random string they'll also configure in the Meta webhook console).

`WhatsAppStatusOut` is the projection both `GET /status` and the
connect/test endpoints return. It DELIBERATELY OMITS `access_token` and
`app_secret` — the encrypted forms live in the DB, plaintext never
leaves the server.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel


WhatsAppIntegrationStatus = Literal[
    "connected", "disconnected", "expired", "error"
]


class WhatsAppConnectIn(BaseModel):
    """HTTP body for `POST /api/v1/integrations/whatsapp/connect`.

    `phone_id` and `waba_id` are pure numeric strings in Meta's docs —
    we keep them as Text to dodge ID-length surprises. `api_version`
    defaults to `v18.0` to match the existing adapter's default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)
    access_token: str = Field(min_length=1)
    app_secret: str = Field(min_length=1, max_length=255)
    verify_token: str = Field(min_length=1, max_length=255)
    api_version: str = Field(default="v18.0", max_length=16)
    # Step 3.5.15 — per-org rate cap (msg/sec). Free-tier ~50, verified
    # accounts up to 1000. Operator-editable; default 50.
    rate_limit_per_sec: int = Field(default=50, ge=1, le=1000)


class EmbeddedSignupExchangeIn(BaseModel):
    """HTTP body for `POST /embedded-signup/exchange`.

    The frontend popup (Step 3) hands us the three values it harvested
    from Meta's FB.login response: the short-lived auth `code`, the
    selected `phone_number_id`, and its parent `waba_id`. The backend
    does the heavy lifting from there — exchange, fetch, subscribe,
    register, persist."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=512)
    phone_number_id: str = Field(min_length=1, max_length=64)
    waba_id: str = Field(min_length=1, max_length=64)


class EmbeddedSignupExchangeOut(BaseModel):
    """Response shape for `POST /embedded-signup/exchange`.

    The Settings UI uses this to render the success state immediately
    after the popup closes — no follow-up `GET /status` call needed.
    `phone_numbers_available` + `selected_index` surface Phase-9-pending
    multi-number context so the frontend can warn the customer when
    their WABA has more phones than we connected."""

    status: WhatsAppIntegrationStatus
    phone_id: str
    waba_id: str
    display_phone_number: str
    verified_name: Optional[str] = None
    api_version: str
    rate_limit_per_sec: int
    phone_numbers_available: int
    selected_index: int
    messaging_limit_tier: Optional[str] = None
    quality_rating: Optional[str] = None


class WhatsAppStatusOut(ORMModel):
    """Projection returned by `connect`, `test`, and `GET /status`.

    NEVER includes `access_token` or `app_secret` — those are encrypted
    at rest and decrypted only inside the dispatch / webhook paths."""

    status: WhatsAppIntegrationStatus
    phone_id: Optional[str] = None
    waba_id: Optional[str] = None
    display_phone_number: Optional[str] = None
    verified_name: Optional[str] = None
    api_version: Optional[str] = None
    rate_limit_per_sec: Optional[int] = None
    last_error: Optional[str] = None
    connected_at: Optional[datetime] = None


WhatsAppTemplateStatus = Literal[
    "APPROVED", "PENDING", "REJECTED", "DISABLED"
]
WhatsAppTemplateCategory = Literal[
    "MARKETING", "UTILITY", "AUTHENTICATION"
]
WhatsAppTemplateHeaderType = Literal[
    "TEXT", "IMAGE", "VIDEO", "DOCUMENT"
]


class WhatsAppTemplateRead(ORMModel):
    """Row projection for `GET /api/v1/integrations/whatsapp/templates`.

    Used by the Settings UI template list (Step 3.5.4) and the campaign
    create-modal picker (Step 3.5.5). `variable_count` lets the picker
    render the right number of variable-binding inputs without parsing
    the body."""

    id: uuid.UUID
    name: str
    language: str
    category: str
    status: str
    body: str
    header_type: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    variable_count: int
    meta_template_id: Optional[str] = None
    last_synced_at: datetime


class WhatsAppTemplateSyncOut(BaseModel):
    """Counts returned by `POST /api/v1/integrations/whatsapp/templates/sync`.

    The Settings UI uses these in a toast: "3 added, 1 updated, 0 removed".
    `total` is the post-sync row count for the org (added + unchanged)."""

    added: int
    updated: int
    removed: int
    total: int


class WhatsAppCapacityOut(BaseModel):
    """Response shape for `GET /api/v1/integrations/whatsapp/capacity`
    — drives the campaign create modal's quota banner (Step 3.5.16).

    `daily_limit` and `remaining` are both `-1` when `is_unlimited`
    is true; the UI uses those sentinels to hide the progress bar
    and the "X remaining" copy. `usage_percent` is capped at 100."""

    tier: str
    tier_label: str
    daily_limit: int
    used_today: int
    remaining: int
    usage_percent: int
    is_unlimited: bool


__all__ = [
    "EmbeddedSignupExchangeIn",
    "EmbeddedSignupExchangeOut",
    "WhatsAppCapacityOut",
    "WhatsAppConnectIn",
    "WhatsAppIntegrationStatus",
    "WhatsAppStatusOut",
    "WhatsAppTemplateCategory",
    "WhatsAppTemplateHeaderType",
    "WhatsAppTemplateRead",
    "WhatsAppTemplateStatus",
    "WhatsAppTemplateSyncOut",
]
