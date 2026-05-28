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

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class WhatsAppStatusOut(BaseModel):
    """Projection returned by `connect`, `test`, and `GET /status`.

    NEVER includes `access_token` or `app_secret` — those are encrypted
    at rest and decrypted only inside the dispatch / webhook paths."""

    model_config = ConfigDict(from_attributes=True)

    status: WhatsAppIntegrationStatus
    phone_id: Optional[str] = None
    waba_id: Optional[str] = None
    display_phone_number: Optional[str] = None
    verified_name: Optional[str] = None
    api_version: Optional[str] = None
    last_error: Optional[str] = None
    connected_at: Optional[datetime] = None


__all__ = [
    "WhatsAppConnectIn",
    "WhatsAppIntegrationStatus",
    "WhatsAppStatusOut",
]
