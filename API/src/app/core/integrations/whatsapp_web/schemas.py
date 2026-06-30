"""Pydantic v2 surface for the WhatsApp Web integration.

Step 4 scope: the response shape that Step 5's status endpoint will
return and the lifecycle enum the router uses for response typing.
Request schemas (Connect / Disconnect bodies) land in Step 5.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WhatsAppWebStatus(str, enum.Enum):
    """Fine-grained Baileys lifecycle exposed to the API surface.

    Mirrors the sidecar's ``SessionStatus`` plus the API-side states::

      - ``pending``       — row created, sidecar not yet acked.
      - ``pairing``       — sidecar booted the socket; QR ready.
      - ``connected``     — phone scanned QR; messages can flow.
      - ``reconnecting``  — transient close, sidecar will retry.
      - ``disconnected``  — operator clicked Disconnect via API.
      - ``logged_out``    — WhatsApp terminated the session; creds wiped.
      - ``error``         — unrecoverable; ``last_error`` carries detail.
    """

    pending = "pending"
    pairing = "pairing"
    connected = "connected"
    reconnecting = "reconnecting"
    disconnected = "disconnected"
    logged_out = "logged_out"
    error = "error"


class WhatsAppWebSessionOut(BaseModel):
    """Response projection for the Step-5 status endpoint.

    Never includes the ``sidecar_session_id`` — that is an internal
    correlation key, not something the SPA should learn or pin to.

    ``qr_data_url`` field shape lands here so Step 6's SSE stream can
    push a value into it without a follow-up schema change. The
    Step-5 endpoints never populate it (QR transport is event-bus →
    SSE, never via REST poll).
    """

    id: UUID
    status: WhatsAppWebStatus
    phone_number: Optional[str] = None
    qr_data_url: Optional[str] = None
    last_event_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WhatsAppWebConnectRequest(BaseModel):
    """Body for ``POST /connect``. Empty for v1 — a future revision
    may carry a human-readable label for the paired number."""

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "WhatsAppWebConnectRequest",
    "WhatsAppWebSessionOut",
    "WhatsAppWebStatus",
]
