"""Pydantic schemas for the quarantine + filter-rules endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.app.shared.schemas.base import ORMModel


RuleType = Literal["allow", "block"]
MatchKind = Literal["email_address", "email_domain", "contact_flag"]
ReasonCode = Literal[
    "size_exceeded",
    "blocked_sender",
    "rate_capped",
    "spam_verdict",
    "virus_verdict",
]
QuarantineStatus = Literal["held", "released", "discarded", "auto_purged"]

# RFC 5321 conservative address bound. Reuse the ``ClaimDomainIn``
# regex for domains but skip the "must have TLD ≥ 2" clause for
# match values since spam-domain tests often use ``.test`` etc.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+"
    r"(?:[A-Za-z]{2,63})$"
)
_CONTACT_FLAG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FilterRuleIn(BaseModel):
    """Payload for ``POST /api/v1/email-filter-rules``.

    Endpoint-scope is optional (``endpoint_id=None`` means org-wide).
    Label is a free-form operator label, not the match value.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rule_type: RuleType
    match_kind: MatchKind
    match_value: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=128)
    endpoint_id: uuid.UUID | None = None

    @field_validator("match_value")
    @classmethod
    def _normalise_match_value(cls, v: str, info) -> str:
        kind = info.data.get("match_kind") if info.data else None
        normalised = v.strip().lower()
        if kind == "email_address":
            if not _EMAIL_RE.match(normalised):
                raise ValueError("match_value must be a valid email address")
        elif kind == "email_domain":
            if not _DOMAIN_RE.match(normalised):
                raise ValueError("match_value must be a valid domain")
        elif kind == "contact_flag":
            if not _CONTACT_FLAG_RE.match(normalised):
                raise ValueError(
                    "match_value must be a lowercase contact flag key"
                )
        return normalised


class FilterRuleOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    endpoint_id: uuid.UUID | None
    rule_type: RuleType
    match_kind: MatchKind
    match_value: str
    label: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class QuarantineOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    endpoint_id: uuid.UUID | None
    mailgun_delivery_id: str | None
    from_address: str
    from_display_name: str | None
    to_recipient: str
    subject: str | None
    body_snippet: str | None
    attachment_summary: list[dict[str, Any]]
    reason_code: ReasonCode
    reason_detail: dict[str, Any]
    status: QuarantineStatus
    blocked_release: bool
    held_at: datetime
    resolved_at: datetime | None
    resolved_by_user_id: uuid.UUID | None


class QuarantineListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[QuarantineOut]
    total: int


class BulkReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class BulkReleaseResult(BaseModel):
    released: list[uuid.UUID]
    rejected: list[dict[str, Any]]  # {"id": ..., "reason": ...}


__all__ = [
    "BulkReleaseIn",
    "BulkReleaseResult",
    "FilterRuleIn",
    "FilterRuleOut",
    "MatchKind",
    "QuarantineListOut",
    "QuarantineOut",
    "QuarantineStatus",
    "ReasonCode",
    "RuleType",
]
