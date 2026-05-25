"""Pydantic v2 schemas for the embeddable-widget keys API.

`EmbedKeyIssue` is the request body for `POST /embed/keys`.
`EmbedKeyRead` is the row projection — used by `GET /embed/keys` and
the side-by-side row in `EmbedKeyIssueResponse`. **`EmbedKeyRead` does
NOT expose the plaintext secret.**
`EmbedKeyIssueResponse` is the response for `POST /embed/keys` only —
it carries the plaintext `secret` exactly once. The secret is never
returned by any other endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmbedKeyIssue(BaseModel):
    """Body for `POST /embed/keys`. `name` is an optional friendly
    label for the Owner to remember what the key is for."""

    name: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(str_strip_whitespace=True)


class EmbedKeyRead(BaseModel):
    """Row projection. Never includes the plaintext secret — only
    the 11-char prefix so the Owner can identify which key is which."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: Optional[str]
    prefix: str
    created_by: uuid.UUID
    last_used_at: Optional[datetime]
    last_used_ip: Optional[str]
    revoked_at: Optional[datetime]
    revoked_by: Optional[uuid.UUID]
    created_at: datetime


class EmbedKeyIssueResponse(BaseModel):
    """Response for `POST /embed/keys` only. The `secret` field
    appears here once and is never retrievable again — the Owner
    must copy it before navigating away."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: Optional[str]
    prefix: str
    secret: str
    created_at: datetime


class SubmissionAttribution(BaseModel):
    """UTM + referrer payload captured by the widget at render time.

    Every field is optional — visitors arriving via direct traffic
    have no UTM parameters or referrer. Step 9's submission log
    surfaces whichever fields landed.

    Schema is frozen for v1 — additional fields land in a separate
    sibling JSON blob rather than expanding this shape, so the
    reporting surface stays stable across channels.
    """

    referrer: Optional[str] = Field(default=None, max_length=2048)
    landing_url: Optional[str] = Field(default=None, max_length=2048)
    utm_source: Optional[str] = Field(default=None, max_length=255)
    utm_medium: Optional[str] = Field(default=None, max_length=255)
    utm_campaign: Optional[str] = Field(default=None, max_length=255)
    utm_content: Optional[str] = Field(default=None, max_length=255)
    utm_term: Optional[str] = Field(default=None, max_length=255)


class EmbedSubmission(BaseModel):
    """Request body for `POST /embed/leads`.

    The widget JS bundle builds this payload from the form values +
    auto-captured attribution data. Authentication is via either the
    `X-FurniCRM-Key` request header OR the `embed_key` body field
    (header takes precedence when both are present).
    """

    embed_key: Optional[str] = Field(default=None, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[EmailStr] = None
    interest: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=2000)
    # Honeypot — bots fill in EVERY visible field including hidden ones.
    # Empty / missing for legit humans. Non-empty triggers a silent 200
    # (no lead created) so bots don't learn they were caught.
    honeypot: Optional[str] = Field(default=None, max_length=255)
    # When the widget rendered the form. Step 8 will use this for a
    # min-time-to-fill check. Step 2 accepts but doesn't enforce.
    rendered_at: Optional[datetime] = None
    attribution: SubmissionAttribution = Field(
        default_factory=SubmissionAttribution
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class EmbedSubmissionResponse(BaseModel):
    """Response for `POST /embed/leads`.

    `ok=True` + `lead_id=None` is the silent-drop case (honeypot
    filled, future spam gates). Real success has both `ok=True` and
    a `lead_id`. The widget treats both as user-visible success so
    bots can't probe for which case they hit.
    """

    ok: bool
    lead_id: Optional[uuid.UUID] = None
    thank_you_url: Optional[str] = None


__all__ = [
    "EmbedKeyIssue",
    "EmbedKeyIssueResponse",
    "EmbedKeyRead",
    "EmbedSubmission",
    "EmbedSubmissionResponse",
    "SubmissionAttribution",
]
