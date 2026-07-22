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
    one table regardless of transport."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["gmail", "microsoft", "smtp"]
    id: str
    from_address: str
    display_name: str | None
    verified: bool
    is_default: bool


__all__ = [
    "SmtpSenderCreate",
    "SmtpSenderOut",
    "SmtpSenderVerify",
    "TlsMode",
    "UnifiedSenderOut",
]
