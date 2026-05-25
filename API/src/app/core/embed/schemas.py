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
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


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
    "WidgetConfigBranding",
    "WidgetConfigField",
    "WidgetConfigPublic",
    "WidgetConfigRead",
    "WidgetConfigUpdate",
]


# --- Widget Config schemas (Step 3) -------------------------------------

# v1 allowed field keys. Adding to this set requires bumping the widget
# JS bundle version since the renderer hardcodes which fields it knows
# how to display. Custom-data field routing is a future surface.
WidgetFieldKey = Literal["full_name", "phone", "email", "interest", "notes"]

# v1 supported field types. The widget bundle hardcodes these — adding
# `date` / `multiselect` / etc. requires a bundle bump.
WidgetFieldType = Literal["text", "email", "tel", "textarea", "select"]


class WidgetConfigField(BaseModel):
    """One configurable field in the rendered widget form.

    `options` is required when `field_type='select'`; ignored otherwise.
    The submission service enforces: every submitted value must come
    from `options` if the field is select-typed.
    """

    key: WidgetFieldKey
    label: str = Field(min_length=1, max_length=128)
    placeholder: Optional[str] = Field(default=None, max_length=128)
    required: bool = False
    order: int = Field(default=0, ge=0, le=999)
    field_type: WidgetFieldType = "text"
    options: Optional[list[str]] = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check_select_options(self) -> "WidgetConfigField":
        """Cross-field invariant: select fields MUST have non-empty
        options; non-select fields MUST NOT carry options. Using a
        model_validator (rather than a field_validator on `options`)
        because Pydantic v2 skips field validators on default values
        — and `options=None` is the default that we need to reject
        when paired with `field_type='select'`.
        """
        if self.field_type == "select":
            if not self.options:
                raise ValueError(
                    "field_type='select' requires a non-empty options list"
                )
        else:
            if self.options:
                raise ValueError(
                    f"options are only allowed for field_type='select', "
                    f"not '{self.field_type}'"
                )
        return self


class WidgetConfigBranding(BaseModel):
    """Visual customisation. The widget bundle exposes these as CSS
    variables (`--fc-primary` etc., wired up in Step 7) so host sites
    can override them too."""

    logo_url: Optional[str] = Field(default=None, max_length=2048)
    accent_color: str = Field(default="#4F46E5", pattern=r"^#[0-9A-Fa-f]{6}$")
    show_powered_by: bool = True


class WidgetConfigDocument(BaseModel):
    """The JSONB-persisted shape — used by both the admin and public
    endpoints. Wraps the field list + branding + UX copy in one object.
    """

    fields: list[WidgetConfigField] = Field(default_factory=list)
    submit_button_label: str = Field(default="Get a quote", min_length=1, max_length=64)
    thank_you_message: str = Field(
        default="Thanks — we'll reach out shortly.",
        min_length=1,
        max_length=512,
    )
    thank_you_url: Optional[str] = Field(default=None, max_length=2048)
    branding: WidgetConfigBranding = Field(default_factory=WidgetConfigBranding)

    @field_validator("fields")
    @classmethod
    def _unique_field_keys(
        cls, value: list[WidgetConfigField]
    ) -> list[WidgetConfigField]:
        keys = [f.key for f in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field keys are not allowed")
        return value


class WidgetConfigUpdate(BaseModel):
    """Body for `PUT /embed/config`. Patch-style — only supplied
    top-level fields are touched; omitted ones stay at their current
    value. The full document is validated after merge.
    """

    fields: Optional[list[WidgetConfigField]] = None
    submit_button_label: Optional[str] = Field(
        default=None, min_length=1, max_length=64
    )
    thank_you_message: Optional[str] = Field(
        default=None, min_length=1, max_length=512
    )
    thank_you_url: Optional[str] = Field(default=None, max_length=2048)
    branding: Optional[WidgetConfigBranding] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class WidgetConfigRead(BaseModel):
    """Admin response. Carries the document + audit metadata."""

    id: uuid.UUID
    org_id: uuid.UUID
    config: WidgetConfigDocument
    updated_by: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class WidgetConfigPublic(BaseModel):
    """Public response — the widget JS bundle's view. No admin
    metadata; just what's needed to render the form."""

    config: WidgetConfigDocument
