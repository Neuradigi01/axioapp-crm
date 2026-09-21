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


# ---------------------------------------------------------------------------
# tasks/email-sending-domains Step 3 — schemas for the new
# ``tbl_organization_email_domains`` flow. Distinct from the legacy
# campaigns-side schemas above; the two shapes intentionally don't
# share a class because they solve different problems (Mailgun-managed
# DNS state vs campaigns' SPF/DKIM verifier).
# ---------------------------------------------------------------------------


from typing import Any, Literal  # noqa: E402


class ClaimDomainIn(BaseModel):
    """Payload for ``POST /api/v1/sender-domains``.

    Region defaults to ``"us"`` — EU tenants must set it explicitly.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    domain: str = Field(min_length=3, max_length=253)
    region: Literal["us", "eu"] = "us"

    @field_validator("domain")
    @classmethod
    def _normalise_and_validate(cls, v: str) -> str:
        normalised = v.lower().rstrip(".")
        if not _DOMAIN_RE.match(normalised):
            raise ValueError("invalid domain shape")
        return normalised


class OrganizationEmailDomainOut(ORMModel):
    """Response shape — deliberately omits ``mailgun_domain_id`` (an
    internal-only identifier). ``dns_records`` is the JSONB column
    rendered verbatim: nested ``sending`` + ``receiving`` arrays with
    the seven Mailgun DnsRecord fields per item.
    """

    id: uuid.UUID
    org_id: uuid.UUID
    domain: str
    verification_status: str
    dns_records: dict[str, Any]
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    last_verified_at: datetime | None
    consecutive_failed_checks: int
    demoted_at: datetime | None
    released_at: datetime | None
    region: str
    created_at: datetime
    updated_at: datetime


EnvelopeType = Literal["smtp_sender", "oauth_account", "own_domain", "platform_from"]


class SendEnvelope(BaseModel):
    """The dispatch envelope returned by ``resolve_send_envelope``.

    ``envelope_type`` picks the outbound path; only the FK / id field
    matching the envelope type is populated. Callers (Step 5's
    ``send_email`` refactor) branch on ``envelope_type`` to choose
    the concrete send backend.

    Never carries secrets — the API key, SMTP password, and OAuth
    refresh token stay behind their respective adapters.
    """

    model_config = ConfigDict(extra="forbid")

    envelope_type: EnvelopeType
    from_address: str
    reply_to: str
    smtp_sender_id: uuid.UUID | None = None
    oauth_account_id: uuid.UUID | None = None
    own_domain_id: uuid.UUID | None = None
    # For ``own_domain`` and ``platform_from`` the caller needs the
    # bare domain so the Mailgun send call can route to the right
    # per-domain endpoint (``POST /v3/{domain}/messages``).
    dispatch_domain: str | None = None
