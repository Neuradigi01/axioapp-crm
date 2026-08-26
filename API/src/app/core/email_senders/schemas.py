"""Pydantic schemas for the ``/email-senders`` endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from src.app.shared.schemas.base import ORMModel


TlsMode = Literal["starttls", "tls", "none"]


class SmtpSenderCreate(BaseModel):
    """Payload for ``POST /email-senders/smtp``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_address: EmailStr
    display_name: str | None = Field(default=None, max_length=128)
    smtp_host: str = Field(min_length=1, max_length=253)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_username: str = Field(min_length=1, max_length=255)
    smtp_password: SecretStr
    tls_mode: TlsMode = "starttls"


class SmtpSenderVerify(BaseModel):
    """Payload for ``POST /email-senders/smtp/{id}/verify`` — the
    6-digit code delivered to ``from_address`` at create time."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^\d{6}$")


class SmtpSenderOut(ORMModel):
    """Response shape — deliberately omits the encrypted password."""

    id: uuid.UUID
    from_address: str
    display_name: str | None
    smtp_host: str
    smtp_port: int
    smtp_username: str
    tls_mode: TlsMode
    verified_at: datetime | None
    is_default: bool
    created_at: datetime


class UnifiedSenderOut(BaseModel):
    """Merged row for the unified sender list — combines verified
    SMTP senders with live OAuth mailboxes so the frontend renders
    one table regardless of transport.

    ``token_expires_at`` / ``sync_state`` / ``last_sync_error`` are
    populated for OAuth rows (gmail / microsoft) and always ``None``
    for SMTP rows (they authenticate per-connect, no long-lived
    session). The card uses them to render a countdown banner + a
    prominent "reconnect required" warning when Google/Microsoft
    revokes the grant — previously the card was silent about token
    health until an actual send failed and the operator dug through
    Celery logs to find the ``invalid_grant`` line.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["gmail", "microsoft", "smtp"]
    id: str
    from_address: str
    display_name: str | None
    verified: bool
    is_default: bool
    # OAuth-only health fields — None for SMTP.
    token_expires_at: datetime | None = None
    sync_state: str | None = None
    last_sync_error: str | None = None


__all__ = [
    "SmtpSenderCreate",
    "SmtpSenderOut",
    "SmtpSenderVerify",
    "TlsMode",
    "UnifiedSenderOut",
]
