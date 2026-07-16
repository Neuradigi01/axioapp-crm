"""Pydantic schemas for the sender-setup endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.shared.schemas.base import ORMModel

# Loose but bounded RFC-1035 domain shape check. The Settings UI
# submits normalised (lowercased, no trailing dot) domains — this
# regex is the last line of defence.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+"
    r"(?:[A-Za-z]{2,63})$"
)


class DomainCreate(BaseModel):
    """Payload for ``POST /email-sender-setup/domains``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    domain: str = Field(min_length=3, max_length=253)

    @field_validator("domain")
    @classmethod
    def _validate_domain_shape(cls, v: str) -> str:
        normalised = v.lower().rstrip(".")
        if not _DOMAIN_RE.match(normalised):
            raise ValueError("invalid domain shape")
        return normalised


class DomainRead(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    domain: str
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    spf_last_checked_at: datetime | None
    dkim_last_checked_at: datetime | None
    dmarc_last_checked_at: datetime | None
    dkim_selector: str
    dkim_public_key: str
    created_at: datetime


class DnsRecord(BaseModel):
    """One DNS record the operator must publish."""

    type: str  # "TXT" or "CNAME"
    host: str
    value: str
    purpose: str  # "spf" | "dkim" | "dmarc"


class DnsRecordsResponse(BaseModel):
    domain: str
    records: list[DnsRecord]


class VerifyResponse(BaseModel):
    """Response for the ``verify`` endpoint. Mirrors ``DomainRead``
    with a ``fully_verified`` convenience so the frontend doesn't
    have to AND the three booleans itself."""

    id: uuid.UUID
    domain: str
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    fully_verified: bool
    last_checked_at: datetime
