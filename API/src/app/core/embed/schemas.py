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
    # When the widget rendered the form. Step 8 enforces a min-fill-time
    # check against this — submissions arriving < `min_fill_time_ms` after
    # render are silently dropped.
    rendered_at: Optional[datetime] = None
    # Google reCAPTCHA v3 token, populated by the widget when the org
    # has enabled reCAPTCHA in their widget config. Verified server-side
    # against the org's secret key; low-score or invalid tokens silent-drop.
    recaptcha_token: Optional[str] = Field(default=None, max_length=4096)
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
    "EmbedSubmissionDayBucket",
    "EmbedSubmissionListResponse",
    "EmbedSubmissionOutcomeLiteral",
    "EmbedSubmissionRead",
    "EmbedSubmissionResponse",
    "EmbedSubmissionSummary",
    "SubmissionAttribution",
    "WidgetConfigBranding",
    "WidgetConfigDocument",
    "WidgetConfigField",
    "WidgetConfigPublic",
    "WidgetConfigPublicDocument",
    "WidgetConfigRead",
    "WidgetConfigSpamProtection",
    "WidgetConfigSpamProtectionPublic",
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


class WidgetConfigSpamProtection(BaseModel):
    """Per-org spam-protection knobs (Step 8). Submitted alongside the
    rest of the widget config; admin endpoints round-trip the full
    shape, the public endpoint projects only `recaptcha_site_key` +
    `min_fill_time_ms` (the secret key MUST stay server-side).

    Defaults: reCAPTCHA off, 2-second min fill time. Honeypot is
    always on — no toggle, no perf cost.
    """

    recaptcha_enabled: bool = False
    recaptcha_site_key: Optional[str] = Field(default=None, max_length=128)
    recaptcha_secret_key: Optional[str] = Field(default=None, max_length=128)
    min_fill_time_ms: int = Field(default=2000, ge=0, le=60000)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def _check_recaptcha_keys(self) -> "WidgetConfigSpamProtection":
        """If reCAPTCHA is enabled, both keys must be set — otherwise
        the gate fails closed on every submission, which silently
        breaks the form for legit users.
        """
        if self.recaptcha_enabled and (
            not self.recaptcha_site_key or not self.recaptcha_secret_key
        ):
            raise ValueError(
                "recaptcha_enabled=true requires both "
                "recaptcha_site_key and recaptcha_secret_key"
            )
        return self


class WidgetConfigSpamProtectionPublic(BaseModel):
    """Public projection — what the widget bundle on a customer's
    website needs to render the reCAPTCHA challenge. Crucially does
    NOT include `recaptcha_secret_key` (admin-only, used server-side
    when calling Google's siteverify).
    """

    recaptcha_enabled: bool = False
    recaptcha_site_key: Optional[str] = None
    min_fill_time_ms: int = 2000


class WidgetConfigDocument(BaseModel):
    """The JSONB-persisted shape — used by the admin endpoints. Wraps
    the field list + branding + spam-protection + UX copy in one
    object. The public endpoint projects this through
    `WidgetConfigPublicDocument` to strip the reCAPTCHA secret.
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
    spam_protection: WidgetConfigSpamProtection = Field(
        default_factory=WidgetConfigSpamProtection
    )

    @field_validator("fields")
    @classmethod
    def _unique_field_keys(
        cls, value: list[WidgetConfigField]
    ) -> list[WidgetConfigField]:
        keys = [f.key for f in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field keys are not allowed")
        return value


class WidgetConfigPublicDocument(BaseModel):
    """Public projection of the document — the secret reCAPTCHA key is
    omitted. Everything else round-trips identically so the widget
    renderer's shape never has to switch on "is this the admin or
    public response".
    """

    fields: list[WidgetConfigField] = Field(default_factory=list)
    submit_button_label: str = "Get a quote"
    thank_you_message: str = "Thanks — we'll reach out shortly."
    thank_you_url: Optional[str] = None
    branding: WidgetConfigBranding = Field(default_factory=WidgetConfigBranding)
    spam_protection: WidgetConfigSpamProtectionPublic = Field(
        default_factory=WidgetConfigSpamProtectionPublic
    )


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
    spam_protection: Optional[WidgetConfigSpamProtection] = None

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
    metadata; just what's needed to render the form. The nested
    `config` uses the public projection so the reCAPTCHA secret
    never reaches a visitor's browser.
    """

    config: WidgetConfigPublicDocument


# --- Submission log (Step 9) ----------------------------------------------


# Mirrors `EmbedSubmissionOutcome` from models.py — duplicated as a
# Literal to avoid importing the SQLAlchemy enum into Pydantic schemas
# (keeps the schema module dependency-free of the ORM).
EmbedSubmissionOutcomeLiteral = Literal[
    "accepted", "rejected_spam", "rate_limited", "invalid_payload"
]


class EmbedSubmissionRead(BaseModel):
    """One row in the paginated list. `lead_id` is set only for
    `outcome='accepted'` rows; the UI surfaces a "View lead" link
    in that column. `ip_hash` is the same 16-hex-char SHA-256
    truncation used everywhere else in the embed module — never
    a raw IP.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key_id: Optional[uuid.UUID]
    lead_id: Optional[uuid.UUID]
    outcome: EmbedSubmissionOutcomeLiteral
    reason: Optional[str]
    ip_hash: Optional[str]
    referrer: Optional[str]
    landing_url: Optional[str]
    created_at: datetime


class EmbedSubmissionListResponse(BaseModel):
    """Envelope for `GET /embed/submissions` — items + total +
    page metadata so the UI can render a "showing 1–25 of N" footer
    without a second round-trip."""

    items: list[EmbedSubmissionRead]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)


class EmbedSubmissionDayBucket(BaseModel):
    """One day's bucket in the summary endpoint's per-day series.
    Used by the stacked bar chart. The `day` is ISO date (UTC)."""

    day: str
    accepted: int = 0
    rejected_spam: int = 0
    rate_limited: int = 0
    invalid_payload: int = 0


class EmbedSubmissionSummary(BaseModel):
    """Response for `GET /embed/submissions/summary` — drives the
    counts card + bar chart at the top of the submission log tab.

    `by_outcome` is the total over the requested window; `by_day`
    is the per-day stacked breakdown (always one entry per day in
    the window, even days with zero submissions, so the chart's
    x-axis is dense).
    """

    range_from: datetime
    range_to: datetime
    by_outcome: dict[EmbedSubmissionOutcomeLiteral, int]
    by_day: list[EmbedSubmissionDayBucket]
